#pragma once

#include "core/symbol/IGroupLinked.h"
#include "screens/alpha_trader/DexterBridge.h"

#include <QJsonObject>
#include <QWidget>

class QLabel;
class QLineEdit;
class QComboBox;
class QSpinBox;
class QPlainTextEdit;
class QPushButton;
class QTableWidget;
class QTimer;
class QButtonGroup;

namespace fincept::screens {

class AlphaTraderChart;

class AlphaTraderScreen : public QWidget, public IGroupLinked {
    Q_OBJECT
    Q_INTERFACES(fincept::IGroupLinked)
  public:
    explicit AlphaTraderScreen(QWidget* parent = nullptr);

    void set_group(SymbolGroup g) override { link_group_ = g; }
    SymbolGroup group() const override { return link_group_; }
    void on_group_symbol_changed(const SymbolRef& ref) override;
    SymbolRef current_symbol() const override;

  private:
    void publish_selection_to_group();
    void refresh();
    void load_chart(const QString& symbol);
    void render_desk(const QJsonObject& payload);
    void set_banner(const QString& text, bool ok);
    void fill_table(QTableWidget* table, const QStringList& headers, const QList<QStringList>& rows);
    void submit_order();
    void send_chat();
    void select_venue(const QString& id, const QString& symbol, bool can_trade);
    void run_action(const QString& kind);

    QLabel* banner_ = nullptr;
    QWidget* venue_bar_ = nullptr;
    QButtonGroup* venue_group_ = nullptr;
    AlphaTraderChart* chart_ = nullptr;
    QComboBox* venue_box_ = nullptr;
    QLineEdit* symbol_edit_ = nullptr;
    QComboBox* side_box_ = nullptr;
    QSpinBox* size_box_ = nullptr;
    QPushButton* buy_btn_ = nullptr;
    QPushButton* sell_btn_ = nullptr;
    QPushButton* autohedge_btn_ = nullptr;
    QPushButton* analyst_btn_ = nullptr;
    QLabel* ticket_status_ = nullptr;
    QPlainTextEdit* chat_log_ = nullptr;
    QLineEdit* chat_input_ = nullptr;
    QTableWidget* blotter_ = nullptr;
    QTableWidget* signals_ = nullptr;
    QTimer* timer_ = nullptr;
    QString selected_venue_ = QStringLiteral("oanda");
    SymbolGroup link_group_ = DexterBridge::desk_group();
};

} // namespace fincept::screens
