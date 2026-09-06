#pragma once

#include <QJsonArray>
#include <QWidget>

class QChart;
class QChartView;
class QCandlestickSeries;
class QValueAxis;
class QBarSet;
class QBarSeries;
class QLabel;

namespace fincept::screens {

class AlphaTraderChart : public QWidget {
    Q_OBJECT
  public:
    explicit AlphaTraderChart(QWidget* parent = nullptr);
    void set_symbol(const QString& symbol);
    void set_candles(const QJsonArray& candles);
    QString symbol() const { return symbol_; }

  private:
    void rebuild();

    QString symbol_;
    QLabel* title_ = nullptr;
    QChartView* view_ = nullptr;
    QChart* chart_ = nullptr;
    QCandlestickSeries* series_ = nullptr;
    QValueAxis* axis_y_ = nullptr;
};

} // namespace fincept::screens
