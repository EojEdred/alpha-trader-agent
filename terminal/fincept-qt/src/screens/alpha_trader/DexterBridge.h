#pragma once

#include "core/symbol/SymbolGroup.h"
#include "core/symbol/SymbolRef.h"
#include "services/markets/MarketDataService.h"
#include "services/news/NewsService.h"

#include <QJsonArray>
#include <QJsonObject>
#include <QObject>
#include <QStringList>
#include <QVector>

class QTimer;

namespace fincept::screens {

/// Shared Dexter loopback client. Pushes quotes onto DataHub so Watchlist,
/// Markets, Dashboard, and Portfolio consume the same tape as the Alpha desk
/// instead of leaving Alpha siloed on its own tab.
class DexterBridge : public QObject {
    Q_OBJECT
  public:
    static DexterBridge& instance();

    static QString base_url();
    static SymbolGroup desk_group() { return SymbolGroup::A; }
    static SymbolRef desk_ref(const QString& symbol);
    static QString crypto_pair_for(const QString& symbol);

    void start();
    QStringList watchlist() const { return watchlist_; }
    QJsonArray last_quotes() const { return last_quotes_; }
    QVector<fincept::services::NewsArticle> last_news() const { return last_news_; }
    QJsonObject last_desk() const { return last_desk_; }

  signals:
    void quotes_updated(const QJsonArray& quotes);
    void news_updated(const QVector<fincept::services::NewsArticle>& articles);
    void desk_updated(const QJsonObject& payload);
    void online_changed(bool ok);

  private:
    explicit DexterBridge(QObject* parent = nullptr);
    void poll_desk();
    void poll_quotes();
    void poll_news();
    void seed_watchlist();
    void publish_quotes(const QJsonArray& quotes);
    static fincept::services::NewsArticle article_from_json(const QJsonObject& o);

    QTimer* quote_timer_ = nullptr;
    QTimer* news_timer_ = nullptr;
    QStringList watchlist_;
    QJsonArray last_quotes_;
    QJsonObject last_desk_;
    QVector<fincept::services::NewsArticle> last_news_;
    bool started_ = false;
    bool seeded_ = false;
};

} // namespace fincept::screens
