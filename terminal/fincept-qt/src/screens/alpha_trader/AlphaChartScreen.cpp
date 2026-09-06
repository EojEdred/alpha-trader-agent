#include "screens/alpha_trader/AlphaChartScreen.h"

#include "core/symbol/SymbolContext.h"
#include "network/http/HttpClient.h"
#include "screens/alpha_trader/DexterBridge.h"
#include "screens/equity_trading/EquityChartPanel.h"
#include "trading/TradingTypes.h"
#include "ui/theme/Theme.h"

#include <QAbstractItemView>
#include <QComboBox>
#include <QDateTime>
#include <QGridLayout>
#include <QGroupBox>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLabel>
#include <QLineEdit>
#include <QListWidget>
#include <QPlainTextEdit>
#include <QPushButton>
#include <QSpinBox>
#include <QSplitter>
#include <QTableWidget>
#include <QTableWidgetItem>
#include <QVBoxLayout>

namespace fincept::screens {

namespace {

QString mono(const QString& color, int px = 12) {
    return QString("color: %1; font-size: %2px; background: transparent; "
                   "font-family: 'Consolas','Courier New',monospace;")
        .arg(color)
        .arg(px);
}

QString table_qss() {
    return QString("QTableWidget { background: %1; color: %2; gridline-color: %3; "
                   "font-family: 'Consolas','Courier New',monospace; font-size: 11px; border: 1px solid %3; }"
                   "QHeaderView::section { background: %4; color: %5; border: 0; padding: 4px; "
                   "font-family: 'Consolas','Courier New',monospace; font-size: 10px; }")
        .arg(ui::colors::BG_SURFACE(), ui::colors::TEXT_PRIMARY(), ui::colors::BORDER_DIM(), ui::colors::BG_RAISED(),
             ui::colors::TEXT_SECONDARY());
}

QGroupBox* box(const QString& title) {
    auto* g = new QGroupBox(title);
    g->setStyleSheet(QString("QGroupBox { color: %1; border: 1px solid %2; margin-top: 10px; "
                             "font-family: 'Consolas','Courier New',monospace; font-size: 11px; font-weight: bold; }"
                             "QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }")
                         .arg(ui::colors::CYAN(), ui::colors::BORDER_DIM()));
    return g;
}

qint64 candle_ms(const QJsonValue& v) {
    if (v.isDouble()) {
        const double d = v.toDouble();
        if (d > 1e12)
            return static_cast<qint64>(d);
        if (d > 1e9)
            return static_cast<qint64>(d * 1000.0);
        return static_cast<qint64>(d);
    }
    const QString s = v.toString();
    QDateTime dt = QDateTime::fromString(s, Qt::ISODateWithMs);
    if (!dt.isValid())
        dt = QDateTime::fromString(s, Qt::ISODate);
    return dt.isValid() ? dt.toMSecsSinceEpoch() : 0;
}

} // namespace

AlphaChartScreen::AlphaChartScreen(QWidget* parent) : QWidget(parent) {
    setObjectName("AlphaChartScreen");
    auto* root = new QVBoxLayout(this);
    root->setContentsMargins(8, 8, 8, 8);
    root->setSpacing(6);

    auto* header = new QHBoxLayout;
    auto* title = new QLabel("CHART");
    title->setStyleSheet(QString("color: %1; font-size: 16px; font-weight: bold; letter-spacing: 2px; "
                                 "background: transparent; font-family: 'Consolas','Courier New',monospace;")
                             .arg(ui::colors::CYAN()));
    header->addWidget(title);
    symbol_edit_ = new QLineEdit("SPY");
    symbol_edit_->setFixedWidth(110);
    symbol_edit_->setStyleSheet(QString("QLineEdit { background: %1; color: %2; border: 1px solid %3; padding: 4px 8px; "
                                        "font-family: 'Consolas','Courier New',monospace; font-size: 13px; font-weight: 700; }")
                                    .arg(ui::colors::BG_RAISED(), ui::colors::TEXT_PRIMARY(), ui::colors::BORDER_DIM()));
    connect(symbol_edit_, &QLineEdit::returnPressed, this, [this]() { on_symbol_chosen(symbol_edit_->text()); });
    header->addWidget(symbol_edit_);
    auto* go = new QPushButton("LOAD");
    go->setStyleSheet(QString("QPushButton { background: %1; color: %2; padding: 4px 10px; "
                              "font-family: 'Consolas','Courier New',monospace; }")
                          .arg(ui::colors::BG_RAISED(), ui::colors::CYAN()));
    connect(go, &QPushButton::clicked, this, [this]() { on_symbol_chosen(symbol_edit_->text()); });
    header->addWidget(go);
    header->addStretch();
    status_ = new QLabel("Dexter chart  ·  15m");
    status_->setStyleSheet(mono(ui::colors::TEXT_TERTIARY()));
    header->addWidget(status_);
    root->addLayout(header);

    auto* split = new QSplitter(Qt::Horizontal);

    watch_ = new QTableWidget;
    watch_->setColumnCount(3);
    watch_->setHorizontalHeaderLabels({"SYM", "LAST", "CHG%"});
    watch_->verticalHeader()->setVisible(false);
    watch_->setEditTriggers(QAbstractItemView::NoEditTriggers);
    watch_->setSelectionBehavior(QAbstractItemView::SelectRows);
    watch_->setSelectionMode(QAbstractItemView::SingleSelection);
    watch_->horizontalHeader()->setStretchLastSection(true);
    watch_->setStyleSheet(table_qss());
    watch_->setMinimumWidth(210);
    connect(watch_, &QTableWidget::cellClicked, this, [this](int row, int) {
        if (auto* item = watch_->item(row, 0))
            on_symbol_chosen(item->text());
    });
    split->addWidget(watch_);

    chart_ = new equity::EquityChartPanel;
    connect(chart_, &equity::EquityChartPanel::timeframe_changed, this, [this](const QString& tf) {
        timeframe_ = tf;
        load_chart();
    });
    connect(chart_, &equity::EquityChartPanel::buy_requested, this, [this](double) { submit_order("long"); });
    connect(chart_, &equity::EquityChartPanel::sell_requested, this, [this](double) { submit_order("short"); });
    split->addWidget(chart_);

    auto* right = new QWidget;
    auto* rl = new QVBoxLayout(right);
    rl->setContentsMargins(0, 0, 0, 0);
    rl->setSpacing(6);

    auto* ticket = box("ORDER");
    auto* tl = new QGridLayout(ticket);
    venue_box_ = new QComboBox;
    venue_box_->addItem("Paper", "paper");
    venue_box_->addItem("OANDA", "oanda");
    venue_box_->addItem("Schwab", "schwab");
    venue_box_->addItem("TopstepX", "topstep");
    size_box_ = new QSpinBox;
    size_box_->setRange(1, 10000);
    size_box_->setValue(1);
    auto* buy = new QPushButton("BUY");
    auto* sell = new QPushButton("SELL");
    buy->setStyleSheet("QPushButton { background: #26a69a; color: #04120f; font-weight: bold; padding: 8px; "
                       "font-family: 'Consolas','Courier New',monospace; }");
    sell->setStyleSheet("QPushButton { background: #ef5350; color: #1a0505; font-weight: bold; padding: 8px; "
                        "font-family: 'Consolas','Courier New',monospace; }");
    connect(buy, &QPushButton::clicked, this, [this]() { submit_order("long"); });
    connect(sell, &QPushButton::clicked, this, [this]() { submit_order("short"); });
    ticket_status_ = new QLabel("Right-click the chart or use BUY/SELL. Dry-run until armed.");
    ticket_status_->setWordWrap(true);
    ticket_status_->setStyleSheet(mono(ui::colors::TEXT_SECONDARY(), 11));
    tl->addWidget(new QLabel("Venue"), 0, 0);
    tl->addWidget(venue_box_, 0, 1);
    tl->addWidget(new QLabel("Size"), 1, 0);
    tl->addWidget(size_box_, 1, 1);
    tl->addWidget(buy, 2, 0);
    tl->addWidget(sell, 2, 1);
    tl->addWidget(ticket_status_, 3, 0, 1, 2);
    rl->addWidget(ticket);

    auto* news_box = box("DEXTER NEWS");
    auto* nl = new QVBoxLayout(news_box);
    news_ = new QListWidget;
    news_->setStyleSheet(QString("QListWidget { background: %1; color: %2; border: none; "
                                 "font-family: 'Consolas','Courier New',monospace; font-size: 11px; }")
                             .arg(ui::colors::BG_BASE(), ui::colors::TEXT_PRIMARY()));
    nl->addWidget(news_);
    rl->addWidget(news_box, 1);

    auto* chat = box("DEXTER");
    auto* cl = new QVBoxLayout(chat);
    chat_log_ = new QPlainTextEdit;
    chat_log_->setReadOnly(true);
    chat_log_->setMaximumHeight(120);
    chat_log_->setStyleSheet(QString("QPlainTextEdit { background: %1; color: %2; border: none; "
                                     "font-family: 'Consolas','Courier New',monospace; font-size: 11px; }")
                                 .arg(ui::colors::BG_BASE(), ui::colors::TEXT_PRIMARY()));
    chat_input_ = new QLineEdit;
    chat_input_->setPlaceholderText("ask Dexter about this chart…");
    connect(chat_input_, &QLineEdit::returnPressed, this, &AlphaChartScreen::send_chat);
    cl->addWidget(chat_log_);
    cl->addWidget(chat_input_);
    rl->addWidget(chat);

    split->addWidget(right);
    split->setStretchFactor(0, 0);
    split->setStretchFactor(1, 1);
    split->setStretchFactor(2, 0);
    split->setSizes({240, 900, 320});
    root->addWidget(split, 1);

    connect(&DexterBridge::instance(), &DexterBridge::quotes_updated, this, &AlphaChartScreen::on_quotes);
    connect(&DexterBridge::instance(), &DexterBridge::news_updated, this,
            [this](const QVector<fincept::services::NewsArticle>& articles) {
                news_->clear();
                for (const auto& a : articles) {
                    auto* item = new QListWidgetItem(a.headline);
                    item->setToolTip(a.summary);
                    news_->addItem(item);
                }
            });
    connect(&DexterBridge::instance(), &DexterBridge::online_changed, this, [this](bool ok) {
        set_status(ok ? QString("DEXTER  ·  %1  ·  %2").arg(symbol_, timeframe_)
                      : QStringLiteral("Dexter down  ·  python cli.py platform start"),
                   ok);
    });
    connect(&DexterBridge::instance(), &DexterBridge::desk_updated, this, [this](const QJsonObject& payload) {
        if (venue_box_->count() > 4)
            return;
        const QJsonArray cards = payload.value("venue_cards").toArray();
        if (cards.isEmpty())
            return;
        venue_box_->clear();
        for (const auto& item : cards) {
            const QJsonObject v = item.toObject();
            venue_box_->addItem(v.value("name").toString(), v.value("id").toString());
        }
    });

    if (!DexterBridge::instance().last_quotes().isEmpty())
        on_quotes(DexterBridge::instance().last_quotes());
    const auto cached_news = DexterBridge::instance().last_news();
    if (!cached_news.isEmpty()) {
        news_->clear();
        for (const auto& a : cached_news) {
            auto* item = new QListWidgetItem(a.headline);
            item->setToolTip(a.summary);
            news_->addItem(item);
        }
    }
    load_chart();
}

void AlphaChartScreen::set_status(const QString& text, bool ok) {
    status_->setText(text);
    status_->setStyleSheet(mono(ok ? ui::colors::CYAN() : ui::colors::TEXT_TERTIARY()));
}

void AlphaChartScreen::on_group_symbol_changed(const SymbolRef& ref) {
    if (!ref.is_valid())
        return;
    const QString incoming = ref.symbol.trimmed().toUpper();
    if (incoming.isEmpty() || incoming == symbol_)
        return;
    symbol_ = incoming;
    if (symbol_edit_)
        symbol_edit_->setText(symbol_);
    load_chart();
}

SymbolRef AlphaChartScreen::current_symbol() const {
    if (symbol_.isEmpty())
        return {};
    return DexterBridge::desk_ref(symbol_);
}

void AlphaChartScreen::publish_selection_to_group() {
    if (link_group_ == SymbolGroup::None)
        return;
    const SymbolRef ref = current_symbol();
    if (ref.is_valid())
        SymbolContext::instance().set_group_symbol(link_group_, ref, this);
}

void AlphaChartScreen::on_symbol_chosen(const QString& symbol) {
    const QString s = symbol.trimmed().toUpper();
    if (s.isEmpty())
        return;
    symbol_ = s;
    symbol_edit_->setText(s);
    publish_selection_to_group();
    load_chart();
}

void AlphaChartScreen::on_quotes(const QJsonArray& quotes) {
    watch_->setRowCount(quotes.size());
    for (int i = 0; i < quotes.size(); ++i) {
        const QJsonObject o = quotes.at(i).toObject();
        const double chg = o.value("change_pct").toDouble();
        auto* sym = new QTableWidgetItem(o.value("symbol").toString());
        auto* last = new QTableWidgetItem(QString::number(o.value("price").toDouble(), 'f', 2));
        auto* pct = new QTableWidgetItem(QString("%1%2%").arg(chg >= 0 ? "+" : "").arg(chg, 0, 'f', 2));
        const QColor col = QColor(chg >= 0 ? "#26a69a" : "#ef5350");
        pct->setForeground(col);
        last->setForeground(col);
        watch_->setItem(i, 0, sym);
        watch_->setItem(i, 1, last);
        watch_->setItem(i, 2, pct);
    }
    watch_->resizeColumnsToContents();
}

void AlphaChartScreen::load_chart() {
    set_status(QString("Loading %1 %2…").arg(symbol_, timeframe_), true);
    const QString url = QString("%1/api/platform/ohlcv?symbol=%2&timespan=%3")
                            .arg(DexterBridge::base_url(), symbol_, timeframe_);
    HttpClient::instance().get(
        url,
        [this](Result<QJsonDocument> result) {
            if (result.is_err()) {
                set_status("Chart fetch failed — is Dexter up?", false);
                return;
            }
            const QJsonObject o = result.value().object();
            const QJsonArray candles = o.value("candles").toArray();
            if (candles.isEmpty() && timeframe_ != QLatin1String("1d")) {
                timeframe_ = QStringLiteral("1d");
                load_chart();
                return;
            }
            const QString shown = o.value("symbol").toString(symbol_);
            apply_candles(candles);
            const QString requested = o.value("requested").toString(symbol_);
            if (shown != requested)
                set_status(QString("%1  ·  proxy %2  ·  %3").arg(requested, shown, timeframe_), true);
            else
                set_status(QString("%1  ·  %2  ·  Dexter/Massive").arg(shown, timeframe_), true);
        },
        this);
}

void AlphaChartScreen::apply_candles(const QJsonArray& candles) {
    QVector<trading::BrokerCandle> bars;
    bars.reserve(candles.size());
    for (const auto& item : candles) {
        const QJsonObject o = item.toObject();
        trading::BrokerCandle c;
        c.timestamp = candle_ms(o.value("timestamp"));
        c.open = o.value("open").toDouble();
        c.high = o.value("high").toDouble();
        c.low = o.value("low").toDouble();
        c.close = o.value("close").toDouble();
        c.volume = o.value("volume").toDouble();
        if (c.high <= 0 || c.low <= 0)
            continue;
        bars.append(c);
    }
    chart_->set_candles(bars);
}

void AlphaChartScreen::submit_order(const QString& side) {
    QJsonObject body;
    body["symbol"] = symbol_;
    body["direction"] = side;
    body["size"] = size_box_->value();
    body["venue"] = venue_box_->currentData().toString();
    ticket_status_->setText("Submitting…");
    HttpClient::instance().post(
        DexterBridge::base_url() + QStringLiteral("/api/platform/execute"), body,
        [this, side](Result<QJsonDocument> result) {
            if (result.is_err()) {
                ticket_status_->setText(QString("Order failed: %1").arg(QString::fromStdString(result.error())));
                return;
            }
            const QJsonObject o = result.value().object();
            ticket_status_->setText(QString("%1  %2 %3 x%4 @ %5  %6")
                                        .arg(o.value("status").toString(), side, o.value("symbol").toString())
                                        .arg(o.value("size").toInt())
                                        .arg(o.value("venue").toString(),
                                             o.value("dry_run").toBool() ? "DRY-RUN" : "LIVE"));
        },
        this);
}

void AlphaChartScreen::send_chat() {
    const QString msg = chat_input_->text().trimmed();
    if (msg.isEmpty())
        return;
    chat_log_->appendPlainText("you  " + msg);
    chat_input_->clear();
    QJsonObject body;
    body["message"] = QString("%1  (chart %2 %3)").arg(msg, symbol_, timeframe_);
    HttpClient::instance().post(
        DexterBridge::base_url() + QStringLiteral("/api/platform/chat"), body,
        [this](Result<QJsonDocument> result) {
            if (result.is_err()) {
                chat_log_->appendPlainText("dexter  (offline) " + QString::fromStdString(result.error()));
                return;
            }
            chat_log_->appendPlainText("dexter  " + result.value().object().value("text").toString());
        },
        this);
}

} // namespace fincept::screens
