#include "screens/alpha_trader/DexterBridge.h"

#include "core/logging/Logger.h"
#include "core/symbol/SymbolContext.h"
#include "datahub/DataHub.h"
#include "datahub/DataHubMetaTypes.h"
#include "network/http/HttpClient.h"
#include "storage/repositories/WatchlistRepository.h"

#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QTimer>
#include <QUrl>

namespace fincept::screens {

DexterBridge& DexterBridge::instance() {
    static DexterBridge inst;
    return inst;
}

QString DexterBridge::base_url() {
    return QStringLiteral("http://127.0.0.1:8080");
}

SymbolRef DexterBridge::desk_ref(const QString& symbol) {
    const QString s = symbol.trimmed().toUpper();
    if (s.contains('/') || s.endsWith(QLatin1String("USDT")) ||
        (s.endsWith(QLatin1String("USD")) && (s.startsWith(QLatin1String("BTC")) || s.startsWith(QLatin1String("ETH")) ||
                                             s.startsWith(QLatin1String("SOL")))))
        return SymbolRef{s, QStringLiteral("crypto"), {}, {}, {}, {}};
    return SymbolRef::equity(s, QStringLiteral("US"));
}

QString DexterBridge::crypto_pair_for(const QString& symbol) {
    const QString s = symbol.trimmed().toUpper().replace("-", "").replace("/", "");
    if (s == QLatin1String("BTC") || s == QLatin1String("BTCUSD") || s == QLatin1String("BTCUSDT") ||
        s == QLatin1String("IBIT"))
        return QStringLiteral("BTC/USDT");
    if (s == QLatin1String("ETH") || s == QLatin1String("ETHUSD") || s == QLatin1String("ETHUSDT"))
        return QStringLiteral("ETH/USDT");
    if (s == QLatin1String("SOL") || s == QLatin1String("SOLUSD") || s == QLatin1String("SOLUSDT"))
        return QStringLiteral("SOL/USDT");
    if (symbol.contains('/'))
        return symbol.trimmed().toUpper();
    return {};
}

DexterBridge::DexterBridge(QObject* parent) : QObject(parent) {
    watchlist_ = QStringList{"SPY", "QQQ", "AAPL", "NVDA", "MSFT", "AMZN", "META", "TSLA", "GLD", "TLT"};
}

void DexterBridge::start() {
    if (started_)
        return;
    started_ = true;
    SymbolContext::instance().set_group_symbol(desk_group(), SymbolRef::equity(QStringLiteral("SPY"), QStringLiteral("US")),
                                               this);

    quote_timer_ = new QTimer(this);
    quote_timer_->setInterval(8000);
    connect(quote_timer_, &QTimer::timeout, this, &DexterBridge::poll_quotes);

    news_timer_ = new QTimer(this);
    news_timer_->setInterval(45000);
    connect(news_timer_, &QTimer::timeout, this, &DexterBridge::poll_news);

    poll_desk();
    poll_quotes();
    poll_news();
    quote_timer_->start();
    news_timer_->start();
    LOG_INFO("DexterBridge", "started — quotes fan out to DataHub market:quote:*");
}

void DexterBridge::poll_desk() {
    HttpClient::instance().get(
        base_url() + QStringLiteral("/api/platform/desk"),
        [this](Result<QJsonDocument> result) {
            if (result.is_err()) {
                emit online_changed(false);
                return;
            }
            const QJsonObject payload = result.value().object();
            emit online_changed(payload.value("ok").toBool(true));
            last_desk_ = payload;
            emit desk_updated(payload);
            QStringList wl;
            for (const auto& v : payload.value("watchlist").toArray()) {
                const QString s = v.toString().trimmed().toUpper();
                if (!s.isEmpty())
                    wl.append(s);
            }
            if (!wl.isEmpty())
                watchlist_ = wl;
            seed_watchlist();
        },
        this);
}

void DexterBridge::seed_watchlist() {
    if (seeded_ || watchlist_.isEmpty())
        return;
    auto& repo = WatchlistRepository::instance();
    auto listed = repo.list_all();
    if (listed.is_err())
        return;
    for (const auto& wl : listed.value()) {
        if (wl.name.compare(QStringLiteral("Alpha Desk"), Qt::CaseInsensitive) == 0) {
            seeded_ = true;
            return;
        }
    }
    auto created = repo.create(QStringLiteral("Alpha Desk"), QStringLiteral("#26a69a"));
    if (created.is_err())
        return;
    const QString id = created.value().id;
    for (const auto& sym : watchlist_)
        repo.add_stock(id, sym, sym, QStringLiteral("US"));
    seeded_ = true;
    LOG_INFO("DexterBridge", QString("seeded Alpha Desk watchlist with %1 symbols").arg(watchlist_.size()));
}

void DexterBridge::poll_quotes() {
    QStringList symbols = watchlist_;
    if (symbols.isEmpty())
        symbols = QStringList{"SPY", "QQQ", "AAPL", "NVDA"};
    const QString url = base_url() + QStringLiteral("/api/platform/quotes?symbols=") +
                        QString::fromUtf8(QUrl::toPercentEncoding(symbols.join(',')));
    HttpClient::instance().get(
        url,
        [this](Result<QJsonDocument> result) {
            if (result.is_err())
                return;
            const QJsonArray quotes = result.value().object().value("quotes").toArray();
            if (quotes.isEmpty())
                return;
            last_quotes_ = quotes;
            publish_quotes(quotes);
            emit quotes_updated(quotes);
            seed_watchlist();
        },
        this);
}

void DexterBridge::publish_quotes(const QJsonArray& quotes) {
    auto& hub = datahub::DataHub::instance();
    for (const auto& item : quotes) {
        const QJsonObject o = item.toObject();
        const QString sym = o.value("symbol").toString();
        if (sym.isEmpty())
            continue;
        services::QuoteData q;
        q.symbol = sym;
        q.name = o.value("name").toString(sym);
        q.price = o.value("price").toDouble();
        q.change = o.value("change").toDouble();
        q.change_pct = o.value("change_pct").toDouble();
        q.high = o.value("high").toDouble();
        q.low = o.value("low").toDouble();
        q.volume = o.value("volume").toDouble();
        hub.publish(QStringLiteral("market:quote:") + sym, QVariant::fromValue(q));
        const QString chart = o.value("chart_symbol").toString();
        if (!chart.isEmpty() && chart != sym)
            hub.publish(QStringLiteral("market:quote:") + chart, QVariant::fromValue(q));
    }
}

void DexterBridge::poll_news() {
    const QString symbol = watchlist_.isEmpty() ? QStringLiteral("SPY") : watchlist_.first();
    HttpClient::instance().get(
        base_url() + QStringLiteral("/api/platform/news?symbol=") + symbol + QStringLiteral("&limit=20"),
        [this](Result<QJsonDocument> result) {
            if (result.is_err())
                return;
            QVector<services::NewsArticle> articles;
            for (const auto& item : result.value().object().value("articles").toArray())
                articles.append(article_from_json(item.toObject()));
            if (!articles.isEmpty()) {
                last_news_ = articles;
                emit news_updated(articles);
            }
        },
        this);
}

fincept::services::NewsArticle DexterBridge::article_from_json(const QJsonObject& o) {
    services::NewsArticle a;
    a.id = o.value("id").toString();
    a.time = o.value("time").toString();
    a.headline = o.value("headline").toString();
    a.summary = o.value("summary").toString();
    a.source = o.value("source").toString(QStringLiteral("Dexter"));
    a.link = o.value("link").toString();
    a.priority = services::Priority::BREAKING;
    a.category = QStringLiteral("EQUITY");
    a.region = QStringLiteral("US");
    for (const auto& t : o.value("tickers").toArray())
        a.tickers.append(t.toString());
    if (a.tickers.isEmpty())
        a.tickers.append(QStringLiteral("SPY"));
    return a;
}

} // namespace fincept::screens
