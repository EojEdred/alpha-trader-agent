#include "screens/alpha_trader/AlphaTraderChart.h"

#include "ui/theme/Theme.h"

#include <QCandlestickSeries>
#include <QCandlestickSet>
#include <QChart>
#include <QChartView>
#include <QDateTime>
#include <QGraphicsLayout>
#include <QJsonArray>
#include <QJsonObject>
#include <QLabel>
#include <QPainter>
#include <QValueAxis>
#include <QVBoxLayout>

namespace fincept::screens {

AlphaTraderChart::AlphaTraderChart(QWidget* parent) : QWidget(parent) {
    auto* root = new QVBoxLayout(this);
    root->setContentsMargins(0, 0, 0, 0);
    root->setSpacing(4);

    title_ = new QLabel("CHART");
    title_->setStyleSheet(QString("color: %1; font-size: 11px; font-weight: bold; letter-spacing: 1px; "
                                  "font-family: 'Consolas','Courier New',monospace; background: transparent;")
                              .arg(ui::colors::TEXT_SECONDARY()));
    root->addWidget(title_);

    chart_ = new QChart();
    chart_->legend()->hide();
    chart_->setBackgroundBrush(QColor(ui::colors::BG_SURFACE()));
    chart_->setPlotAreaBackgroundBrush(QColor(ui::colors::BG_BASE()));
    chart_->setPlotAreaBackgroundVisible(true);
    chart_->setBackgroundRoundness(0);
    chart_->setMargins(QMargins(0, 0, 0, 0));
    chart_->layout()->setContentsMargins(0, 0, 0, 0);

    series_ = new QCandlestickSeries();
    series_->setIncreasingColor(QColor("#26a69a"));
    series_->setDecreasingColor(QColor("#ef5350"));
    series_->setBodyOutlineVisible(false);
    series_->setCapsVisible(false);
    chart_->addSeries(series_);

    axis_y_ = new QValueAxis();
    axis_y_->setLabelFormat("%.2f");
    axis_y_->setLabelsColor(QColor(ui::colors::TEXT_SECONDARY()));
    axis_y_->setGridLineColor(QColor(ui::colors::BORDER_DIM()));
    axis_y_->setLineVisible(false);
    chart_->addAxis(axis_y_, Qt::AlignRight);
    series_->attachAxis(axis_y_);

    view_ = new QChartView(chart_);
    view_->setRenderHint(QPainter::Antialiasing);
    view_->setStyleSheet("background: transparent; border: none;");
    view_->setMinimumHeight(280);
    root->addWidget(view_, 1);
}

void AlphaTraderChart::set_symbol(const QString& symbol) {
    symbol_ = symbol;
    title_->setText(QString("CHART  ·  %1  ·  1D").arg(symbol_));
}

void AlphaTraderChart::set_candles(const QJsonArray& candles) {
    series_->clear();
    double lo = 1e18;
    double hi = -1e18;
    int i = 0;
    for (const auto& item : candles) {
        const QJsonObject o = item.toObject();
        const double o_ = o.value("open").toDouble();
        const double h_ = o.value("high").toDouble();
        const double l_ = o.value("low").toDouble();
        const double c_ = o.value("close").toDouble();
        if (h_ <= 0 || l_ <= 0)
            continue;
        auto* set = new QCandlestickSet(o_, h_, l_, c_, i++);
        series_->append(set);
        lo = qMin(lo, l_);
        hi = qMax(hi, h_);
    }
    if (hi > lo) {
        const double pad = (hi - lo) * 0.08;
        axis_y_->setRange(lo - pad, hi + pad);
    }
    title_->setText(QString("CHART  ·  %1  ·  1D  ·  %2 bars").arg(symbol_).arg(series_->count()));
}

} // namespace fincept::screens
