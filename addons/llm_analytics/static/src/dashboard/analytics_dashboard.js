/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { formatFloat, formatInteger } from "@web/views/fields/formatters";

class AnalyticsDashboard extends Component {
    static template = "llm_analytics.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");

        this.state = useState({
            loading: true,
            period: "month",
            stats: {
                total_requests: 0,
                total_tokens: 0,
                total_cost: 0,
                avg_response_time: 0,
                success_rate: 0,
                total_likes: 0,
                total_dislikes: 0,
            },
            chartData: {
                daily: [],
                byModel: [],
                byUser: [],
            },
        });

        onWillStart(async () => {
            await this.loadData();
        });
    }

    async loadData() {
        this.state.loading = true;
        try {
            const data = await this.orm.call(
                "llm.usage.log",
                "get_dashboard_data",
                [this.state.period]
            );
            this.state.stats = data.stats;
            this.state.chartData = data.charts;
        } catch (error) {
            console.error("Failed to load dashboard data:", error);
        }
        this.state.loading = false;
    }

    async onPeriodChange(period) {
        this.state.period = period;
        await this.loadData();
    }

    formatNumber(value) {
        if (value >= 1000000) {
            return (value / 1000000).toFixed(1) + "M";
        } else if (value >= 1000) {
            return (value / 1000).toFixed(1) + "K";
        }
        return formatInteger(value);
    }

    formatCost(value) {
        if (!value || value === 0) {
            return "$0.00";
        }
        return "$" + formatFloat(value, { digits: [0, 6] });
    }

    formatTime(value) {
        if (!value || value === 0) {
            return "0s";
        }
        if (value < 1) {
            return (value * 1000).toFixed(0) + "ms";
        }
        return formatFloat(value, { digits: [0, 2] }) + "s";
    }

    formatPercent(value) {
        return formatFloat(value || 0, { digits: [0, 1] }) + "%";
    }

    openRequests(domain = []) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Requests",
            res_model: "llm.usage.log",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain: domain,
            context: {},
        });
    }

    openLiked() {
        this.openRequests([["feedback", "=", "like"]]);
    }

    openDisliked() {
        this.openRequests([["feedback", "=", "dislike"]]);
    }
}

registry.category("actions").add("llm_analytics_dashboard", AnalyticsDashboard);
