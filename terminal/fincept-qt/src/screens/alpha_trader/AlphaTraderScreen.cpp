#include "screens/alpha_trader/AlphaTraderScreen.h"

#include "core/symbol/SymbolContext.h"
#include "network/http/HttpClient.h"
#include "screens/alpha_trader/AlphaTraderChart.h"
#include "ui/theme/Theme.h"

#include <QAbstractItemView>
#include <QButtonGroup>
#include <QComboBox>
#include <QGridLayout>
#include <QGroupBox>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLabel>
#include <QLineEdit>
#include <QPlainTextEdit>
#include <QPushButton>
#include <QScrollArea>
#include <QSpinBox>
#include <QTableWidget>
#include <QTableWidgetItem>
#include <QTimer>
#include <QVBoxLayout>

namespace fincept::screens {

static QString mono(const QString& color, int px = 12) {
    return QString("color: %1; font-size: %2px; background: transparent; "
                   "font-family: 'Consolas','Courier New',monospace;")
        .arg(color)
        .arg(px);
}

static QString table_qss() {
    return QString("QTableWidget { background: %1; color: %2; gridline-color: %3; "
                   "font-family: 'Consolas','Courier New',monospace; font-size: 11px; border: 1px solid %3; }"
                   "QHeaderView::section { background: %4; color: %5; border: 0; padding: 4px; "
                   "font-family: 'Consolas','Courier New',monospace; font-size: 10px; }")
        .arg(ui::colors::BG_SURFACE(), ui::colors::TEXT_PRIMARY(), ui::colors::BORDER_DIM(),
             ui::colors::BG_RAISED(), ui::colors::TEXT_SECONDARY());
}

static QGroupBox* box(const QString& title) {
    auto* g = new QGroupBox(title);
    g->setStyleSheet(QString("QGroupBox { color: %1; border: 1px solid %2; margin-top: 10px; "
                             "font-family: 'Consolas','Courier New',monospace; font-size: 11px; font-weight: bold; }"
                             "QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }")
                         .arg(ui::colors::CYAN(), ui::colors::BORDER_DIM()));
    return g;
}

static QString chip_qss(bool on) {
    const QString bg = on ? "rgba(38,166,154,0.18)" : ui::colors::BG_RAISED();
    const QString fg = on ? "#26a69a" : ui::colors::TEXT_SECONDARY();
    const QString bd = on ? "#26a69a" : ui::colors::BORDER_DIM();
    return QString("QPushButton { background: %1; color: %2; border: 1px solid %3; padding: 6px 10px; "
                   "font-family: 'Consolas','Courier New',monospace; font-size: 11px; }"
                   "QPushButton:checked { background: rgba(56,189,248,0.16); color: %4; border-color: %4; }")
        .arg(bg, fg, bd, ui::colors::CYAN());
}

AlphaTraderScreen::AlphaTraderScreen(QWidget* parent) : QWidget(parent) {
    setObjectName("AlphaTraderScreen");
    auto* root = new QVBoxLayout(this);
    root->setContentsMargins(12, 12, 12, 12);
    root->setSpacing(8);

    auto* header = new QHBoxLayout;
    auto* title = new QLabel("ALPHA TRADER");
    title->setStyleSheet(QString("color: %1; font-size: 18px; font-weight: bold; letter-spacing: 2px; "
                                 "background: transparent; font-family: 'Consolas','Courier New',monospace;")
                             .arg(ui::colors::CYAN()));
    header->addWidget(title);
    header->addStretch();
    banner_ = new QLabel("Connecting to Dexter  ·  quotes also drive CHART / WATCH / MARKETS / DASH…");
    banner_->setStyleSheet(mono(ui::colors::TEXT_TERTIARY()));
    header->addWidget(banner_);
    root->addLayout(header);

    auto* venue_scroll = new QScrollArea;
    venue_scroll->setWidgetResizable(true);
    venue_scroll->setHorizontalScrollBarPolicy(Qt::ScrollBarAsNeeded);
    venue_scroll->setVerticalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    venue_scroll->setFixedHeight(64);
    venue_scroll->setStyleSheet("QScrollArea { border: none; background: transparent; }");
    venue_bar_ = new QWidget;
    auto* venue_layout = new QHBoxLayout(venue_bar_);
    venue_layout->setContentsMargins(0, 0, 0, 0);
    venue_layout->setSpacing(6);
    venue_group_ = new QButtonGroup(this);
    venue_group_->setExclusive(true);
    venue_scroll->setWidget(venue_bar_);
    root->addWidget(venue_scroll);

    auto* mid = new QHBoxLayout;
    chart_ = new AlphaTraderChart;
    chart_->set_symbol("SPY");
    mid->addWidget(chart_, 3);

    auto* right = new QVBoxLayout;

    auto* ticket = box("ORDER TICKET");
    auto* tl = new QGridLayout(ticket);
    venue_box_ = new QComboBox;
    symbol_edit_ = new QLineEdit("EURUSD");
    side_box_ = new QComboBox;
    side_box_->addItems({"long", "short"});
    size_box_ = new QSpinBox;
    size_box_->setRange(1, 10000);
    size_box_->setValue(1);
    buy_btn_ = new QPushButton("BUY / LONG");
    sell_btn_ = new QPushButton("SELL / SHORT");
    buy_btn_->setStyleSheet("QPushButton { background: #26a69a; color: #04120f; font-weight: bold; padding: 8px; "
                            "font-family: 'Consolas','Courier New',monospace; }");
    sell_btn_->setStyleSheet("QPushButton { background: #ef5350; color: #1a0505; font-weight: bold; padding: 8px; "
                             "font-family: 'Consolas','Courier New',monospace; }");
    ticket_status_ = new QLabel("Dry-run until you arm live.");
    ticket_status_->setStyleSheet(mono(ui::colors::TEXT_SECONDARY(), 11));
    ticket_status_->setWordWrap(true);
    tl->addWidget(new QLabel("Venue"), 0, 0);
    tl->addWidget(venue_box_, 0, 1);
    tl->addWidget(new QLabel("Symbol"), 1, 0);
    tl->addWidget(symbol_edit_, 1, 1);
    tl->addWidget(new QLabel("Size"), 2, 0);
    tl->addWidget(size_box_, 2, 1);
    autohedge_btn_ = new QPushButton("RUN AUTOHEDGE");
    analyst_btn_ = new QPushButton("RUN ANALYST");
    autohedge_btn_->setStyleSheet(QString("QPushButton { background: %1; color: %2; padding: 8px; "
                                          "font-family: 'Consolas','Courier New',monospace; }")
                                      .arg(ui::colors::BG_RAISED(), ui::colors::CYAN()));
    analyst_btn_->setStyleSheet(autohedge_btn_->styleSheet());
    tl->addWidget(buy_btn_, 3, 0);
    tl->addWidget(sell_btn_, 3, 1);
    tl->addWidget(autohedge_btn_, 4, 0);
    tl->addWidget(analyst_btn_, 4, 1);
    tl->addWidget(ticket_status_, 5, 0, 1, 2);
    connect(autohedge_btn_, &QPushButton::clicked, this, [this]() { run_action("autohedge"); });
    connect(analyst_btn_, &QPushButton::clicked, this, [this]() { run_action("analyst"); });
    connect(buy_btn_, &QPushButton::clicked, this, [this]() {
        side_box_->setCurrentText("long");
        submit_order();
    });
    connect(sell_btn_, &QPushButton::clicked, this, [this]() {
        side_box_->setCurrentText("short");
        submit_order();
    });
    right->addWidget(ticket);

    auto* chat = box("DEXTER BRAIN");
    auto* cl = new QVBoxLayout(chat);
    chat_log_ = new QPlainTextEdit;
    chat_log_->setReadOnly(true);
    chat_log_->setStyleSheet(QString("QPlainTextEdit { background: %1; color: %2; border: none; "
                                     "font-family: 'Consolas','Courier New',monospace; font-size: 12px; }")
                                 .arg(ui::colors::BG_BASE(), ui::colors::TEXT_PRIMARY()));
    chat_input_ = new QLineEdit;
    chat_input_->setPlaceholderText("ask Dexter  ·  also: python cli.py ask \"...\"");
    connect(chat_input_, &QLineEdit::returnPressed, this, &AlphaTraderScreen::send_chat);
    cl->addWidget(chat_log_, 1);
    cl->addWidget(chat_input_);
    right->addWidget(chat, 1);
    mid->addLayout(right, 2);
    root->addLayout(mid, 3);

    auto* bottom = new QHBoxLayout;
    auto* blotter_box = box("PAPER / LIVE BLOTTER");
    auto* bl = new QVBoxLayout(blotter_box);
    blotter_ = new QTableWidget;
    blotter_->setStyleSheet(table_qss());
    blotter_->verticalHeader()->setVisible(false);
    blotter_->setEditTriggers(QAbstractItemView::NoEditTriggers);
    blotter_->setSelectionBehavior(QAbstractItemView::SelectRows);
    blotter_->horizontalHeader()->setStretchLastSection(true);
    bl->addWidget(blotter_);
    bottom->addWidget(blotter_box, 1);

    auto* sig_box = box("SIGNALS");
    auto* sl = new QVBoxLayout(sig_box);
    signals_ = new QTableWidget;
    signals_->setStyleSheet(table_qss());
    signals_->verticalHeader()->setVisible(false);
    signals_->setEditTriggers(QAbstractItemView::NoEditTriggers);
    signals_->setSelectionBehavior(QAbstractItemView::SelectRows);
    signals_->horizontalHeader()->setStretchLastSection(true);
    sl->addWidget(signals_);
    bottom->addWidget(sig_box, 1);
    root->addLayout(bottom, 2);

    timer_ = new QTimer(this);
    timer_->setInterval(4000);
    connect(timer_, &QTimer::timeout, this, &AlphaTraderScreen::refresh);
    timer_->start();
    refresh();
    load_chart("SPY");
}

void AlphaTraderScreen::set_banner(const QString& text, bool ok) {
    banner_->setText(text);
    banner_->setStyleSheet(mono(ok ? ui::colors::CYAN() : ui::colors::TEXT_TERTIARY()));
}

void AlphaTraderScreen::fill_table(QTableWidget* table, const QStringList& headers,
                                   const QList<QStringList>& rows) {
    table->setColumnCount(headers.size());
    table->setHorizontalHeaderLabels(headers);
    table->setRowCount(rows.size());
    for (int r = 0; r < rows.size(); ++r)
        for (int c = 0; c < headers.size() && c < rows[r].size(); ++c)
            table->setItem(r, c, new QTableWidgetItem(rows[r][c]));
    table->resizeColumnsToContents();
}

void AlphaTraderScreen::select_venue(const QString& id, const QString& symbol, bool can_trade) {
    selected_venue_ = id;
    const int idx = venue_box_->findData(id);
    if (idx >= 0)
        venue_box_->setCurrentIndex(idx);
    buy_btn_->setEnabled(can_trade);
    sell_btn_->setEnabled(can_trade);
    ticket_status_->setText(can_trade ? QString("Ready on %1").arg(id)
                                      : QString("%1 is data/research — use AutoHedge / Analyst / chat").arg(id));
    if (!symbol.isEmpty()) {
        symbol_edit_->setText(symbol);
        load_chart(symbol);
    }
}

void AlphaTraderScreen::run_action(const QString& kind) {
    QJsonObject body;
    body["kind"] = kind;
    body["symbol"] = symbol_edit_->text().trimmed();
    body["task"] = QString("%1 %2").arg(kind, symbol_edit_->text().trimmed());
    ticket_status_->setText("Running " + kind + "…");
    chat_log_->appendPlainText("you  run " + kind + " " + symbol_edit_->text());
    HttpClient::instance().post(
        "http://127.0.0.1:8080/api/platform/action", body,
        [this, kind](Result<QJsonDocument> result) {
            if (result.is_err()) {
                ticket_status_->setText(kind + " failed");
                chat_log_->appendPlainText("dexter  " + QString::fromStdString(result.error()));
                return;
            }
            const QJsonObject o = result.value().object();
            ticket_status_->setText(kind + "  " + o.value("status").toString());
            chat_log_->appendPlainText("dexter  " + QString::fromUtf8(QJsonDocument(o).toJson(QJsonDocument::Compact)));
        },
        this);
}

void AlphaTraderScreen::on_group_symbol_changed(const SymbolRef& ref) {
    if (!ref.is_valid())
        return;
    if (symbol_edit_ && symbol_edit_->text().compare(ref.symbol, Qt::CaseInsensitive) == 0)
        return;
    if (symbol_edit_)
        symbol_edit_->setText(ref.symbol);
    load_chart(ref.symbol);
}

SymbolRef AlphaTraderScreen::current_symbol() const {
    const QString s = symbol_edit_ ? symbol_edit_->text().trimmed() : QString();
    if (s.isEmpty())
        return {};
    return DexterBridge::desk_ref(s);
}

void AlphaTraderScreen::publish_selection_to_group() {
    if (link_group_ == SymbolGroup::None)
        return;
    const SymbolRef ref = current_symbol();
    if (ref.is_valid())
        SymbolContext::instance().set_group_symbol(link_group_, ref, this);
}

void AlphaTraderScreen::load_chart(const QString& symbol) {
    chart_->set_symbol(symbol);
    publish_selection_to_group();
    const QString url = QString("http://127.0.0.1:8080/api/platform/ohlcv?symbol=%1&days=90").arg(symbol);
    HttpClient::instance().get(
        url,
        [this, symbol](Result<QJsonDocument> result) {
            if (result.is_err())
                return;
            const QJsonObject o = result.value().object();
            chart_->set_symbol(o.value("symbol").toString(symbol));
            chart_->set_candles(o.value("candles").toArray());
        },
        this);
}

void AlphaTraderScreen::submit_order() {
    QJsonObject body;
    body["symbol"] = symbol_edit_->text().trimmed();
    body["direction"] = side_box_->currentText();
    body["size"] = size_box_->value();
    body["venue"] = venue_box_->currentData().toString();
    if (body["venue"].toString().isEmpty())
        body["venue"] = selected_venue_;
    ticket_status_->setText("Submitting…");
    HttpClient::instance().post(
        "http://127.0.0.1:8080/api/platform/execute", body,
        [this](Result<QJsonDocument> result) {
            if (result.is_err()) {
                ticket_status_->setText(QString("Order failed: %1").arg(QString::fromStdString(result.error())));
                return;
            }
            const QJsonObject o = result.value().object();
            ticket_status_->setText(QString("%1  %2 %3 x%4 @ %5  %6")
                                        .arg(o.value("status").toString(), o.value("direction").toString(),
                                             o.value("symbol").toString())
                                        .arg(o.value("size").toInt())
                                        .arg(o.value("venue").toString(),
                                             o.value("dry_run").toBool() ? "DRY-RUN" : "LIVE"));
            refresh();
        },
        this);
}

void AlphaTraderScreen::send_chat() {
    const QString msg = chat_input_->text().trimmed();
    if (msg.isEmpty())
        return;
    chat_log_->appendPlainText("you  " + msg);
    chat_input_->clear();
    QJsonObject body;
    body["message"] = msg;
    HttpClient::instance().post(
        "http://127.0.0.1:8080/api/platform/chat", body,
        [this](Result<QJsonDocument> result) {
            if (result.is_err()) {
                chat_log_->appendPlainText("dexter  (offline) " + QString::fromStdString(result.error()));
                return;
            }
            chat_log_->appendPlainText("dexter  " + result.value().object().value("text").toString());
        },
        this);
}

void AlphaTraderScreen::refresh() {
    HttpClient::instance().get(
        "http://127.0.0.1:8080/api/platform/desk",
        [this](Result<QJsonDocument> result) {
            if (result.is_err()) {
                set_banner("Dexter down  ·  python cli.py platform start", false);
                return;
            }
            render_desk(result.value().object());
        },
        this);
}

void AlphaTraderScreen::render_desk(const QJsonObject& payload) {
    const bool ok = payload.value("ok").toBool();
    const bool dry = payload.value("dry_run").toBool();
    set_banner(QString("%1  ·  %2  ·  127.0.0.1:8080")
                   .arg(ok ? QStringLiteral("DEXTER ONLINE") : QStringLiteral("DEGRADED"),
                        dry ? QStringLiteral("DRY-RUN") : QStringLiteral("LIVE GATE")),
               ok);

    auto* layout = qobject_cast<QHBoxLayout*>(venue_bar_->layout());
    const QJsonArray cards = payload.value("venue_cards").toArray();
    if (venue_box_->count() == 0) {
        for (const auto& item : cards) {
            const QJsonObject v = item.toObject();
            venue_box_->addItem(QString("%1  ·  %2").arg(v.value("name").toString(), v.value("cls").toString()),
                                v.value("id").toString());
        }
    }
    if (layout && layout->count() == 0) {
        int i = 0;
        for (const auto& item : cards) {
            const QJsonObject v = item.toObject();
            const bool on = v.value("connected").toBool();
            auto* btn = new QPushButton(QString("%1\n%2").arg(v.value("name").toString(), on ? "ON" : "OFF"));
            btn->setCheckable(true);
            btn->setStyleSheet(chip_qss(on));
            const QString id = v.value("id").toString();
            const QString sym = v.value("symbol").toString();
            const bool can_trade = v.value("execute").toBool() && on;
            venue_group_->addButton(btn, i++);
            connect(btn, &QPushButton::clicked, this, [this, id, sym, can_trade]() { select_venue(id, sym, can_trade); });
            layout->addWidget(btn);
        }
        layout->addStretch();
    }

    QList<QStringList> blotter_rows;
    for (const auto& item : payload.value("paper_trades").toArray()) {
        const QJsonObject o = item.toObject();
        blotter_rows << QStringList{o.value("timestamp").toString().left(19), o.value("symbol").toString(),
                                    o.value("source").toString(), o.value("direction").toString(),
                                    o.value("entry").toString(), o.value("stop").toString(),
                                    o.value("target").toString()};
    }
    fill_table(blotter_, {"TIME", "SYMBOL", "SRC", "DIR", "ENTRY", "STOP", "TARGET"}, blotter_rows);

    QList<QStringList> sig_rows;
    for (const auto& item : payload.value("signals").toArray()) {
        const QJsonObject o = item.toObject();
        sig_rows << QStringList{o.value("timestamp").toString().left(19), o.value("symbol").toString(),
                                o.value("source").toString(), o.value("direction").toString(),
                                QString::number(o.value("confidence").toDouble(), 'f', 2)};
    }
    fill_table(signals_, {"TIME", "SYMBOL", "SRC", "DIR", "CONF"}, sig_rows);
}

} // namespace fincept::screens
