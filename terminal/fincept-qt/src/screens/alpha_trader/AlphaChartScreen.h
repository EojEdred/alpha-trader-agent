#pragma once

#include "core/symbol/IGroupLinked.h"
#include "screens/alpha_trader/DexterBridge.h"

#include <QJsonArray>
#include <QWidget>

class QLabel;
class QLineEdit;
class QComboBox;
class QSpinBox;
class QPushButton;
class QTableWidget;
class QListWidget;
class QPlainTextEdit;

namespace fincept::screens::equity {
class EquityChartPanel;
}

namespace fincept::screens {

class AlphaChartScreen : public QWidget, public IGroupLinked {
    Q_OBJECT
    Q_INTERFACES(fincept::IGroupLinked)
  public:
    explicit AlphaChartScreen(QWidget* parent = nullptr);

    void set_group(SymbolGroup g) override { link_group_ = g; }
    SymbolGroup group() const override { return link_group_; }
    void on_group_symbol_changed(const SymbolRef& ref) override;
    SymbolRef current_symbol() const override;

  private:
    void publish_selection_to_group();
    void load_chart();
    void on_symbol_chosen(const QString& symbol);
    void on_quotes(const QJsonArray& quotes);
    void submit_order(const QString& side);
    void send_chat();
    void apply_candles(const QJsonArray& candles);
    void set_status(const QString& text, bool ok);

    QString symbol_ = QStringLiteral("SPY");
    QString timeframe_ = QStringLiteral("15m");

    QLabel* status_ = nullptr;
    QLineEdit* symbol_edit_ = nullptr;
    QTableWidget* watch_ = nullptr;
    equity::EquityChartPanel* chart_ = nullptr;
    QComboBox* venue_box_ = nullptr;
    QSpinBox* size_box_ = nullptr;
    QLabel* ticket_status_ = nullptr;
    QListWidget* news_ = nullptr;
    QPlainTextEdit* chat_log_ = nullptr;
    QLineEdit* chat_input_ = nullptr;
    SymbolGroup link_group_ = DexterBridge::desk_group();
};
} // namespace fincept::screens
