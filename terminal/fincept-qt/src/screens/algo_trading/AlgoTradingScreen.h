// src/screens/algo_trading/AlgoTradingScreen.h
#pragma once
#include "core/symbol/IGroupLinked.h"
#include "screens/algo_trading/AlertsPanel.h"
#include "screens/alpha_trader/DexterBridge.h"
#include "screens/common/IStatefulScreen.h"
#include "services/algo_trading/AlgoTradingTypes.h"

#include <QEvent>
#include <QHideEvent>
#include <QLabel>
#include <QPushButton>
#include <QShowEvent>
#include <QStackedWidget>
#include <QTimer>
#include <QWidget>

namespace fincept::screens {

class StrategyBuilderPanel;
class StrategyListPanel;
class ScannerPanel;
class DeploymentDashboard;
class UniverseScannerPanel;

/// Algo Trading screen — 6-tab trading system builder.
/// Tabs: Builder, My Strategies, Scanner, Alerts, Dashboard, Universe
class AlgoTradingScreen : public QWidget, public IStatefulScreen, public IGroupLinked {
    Q_OBJECT
    Q_INTERFACES(fincept::IGroupLinked)
  public:
    explicit AlgoTradingScreen(QWidget* parent = nullptr);

    void set_group(SymbolGroup g) override { link_group_ = g; }
    SymbolGroup group() const override { return link_group_; }
    void on_group_symbol_changed(const SymbolRef& ref) override;
    SymbolRef current_symbol() const override;

    void restore_state(const QVariantMap& state) override;
    QVariantMap save_state() const override;
    QString state_key() const override { return "algo_trading"; }
    int state_version() const override { return 1; }

  protected:
    void showEvent(QShowEvent* event) override;
    void hideEvent(QHideEvent* event) override;
    void changeEvent(QEvent* event) override;

  private slots:
    void on_tab_changed(int index);

  private:
    void build_ui();
    QWidget* build_top_bar();
    QWidget* build_status_bar();
    void update_tab_buttons();
    /// Re-render the running-deployment badge. Red "N LIVE" only when real-money
    /// deployments are running; green "N PAPER" otherwise.
    void update_deploy_badge();
    void retranslateUi();

    QStackedWidget* content_stack_ = nullptr;
    StrategyBuilderPanel* builder_ = nullptr;
    StrategyListPanel* strategies_ = nullptr;
    ScannerPanel* scanner_ = nullptr;
    AlertsPanel* alerts_ = nullptr;
    DeploymentDashboard* dashboard_ = nullptr;
    UniverseScannerPanel* universe_ = nullptr;

    QVector<QPushButton*> tab_buttons_;
    int active_tab_ = 0;
    int active_deployments_ = 0;
    int live_deployments_ = 0;
    QLabel* title_label_ = nullptr;
    QLabel* engine_caption_ = nullptr;
    QLabel* deploy_count_label_ = nullptr;
    QLabel* status_label_ = nullptr;
    QTimer* poll_timer_ = nullptr;
    bool first_show_ = true;
    SymbolGroup link_group_ = DexterBridge::desk_group();
    QString linked_symbol_;
    QLabel* dexter_label_ = nullptr;
};

} // namespace fincept::screens
