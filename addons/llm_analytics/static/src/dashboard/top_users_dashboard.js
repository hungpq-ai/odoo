/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { formatFloat, formatInteger } from "@web/views/fields/formatters";

class TopUsersDashboard extends Component {
    static template = "llm_analytics.TopUsersDashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");

        this.state = useState({
            loading: true,
            period: "month",
            users: [],
            totals: {
                requests: 0,
                tokens: 0,
                cost: 0,
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
                "get_top_users_data",
                [this.state.period]
            );
            this.state.users = data.users;
            this.state.totals = data.totals;
        } catch (error) {
            console.error("Failed to load top users data:", error);
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

    formatPercent(value) {
        return formatFloat(value || 0, { digits: [0, 1] }) + "%";
    }

    getRankBadgeClass(rank) {
        if (rank === 1) return "bg-warning text-dark";
        if (rank === 2) return "bg-secondary";
        if (rank === 3) return "bg-danger";
        return "bg-primary";
    }

    getRankIcon(rank) {
        if (rank === 1) return "fa-trophy";
        if (rank === 2) return "fa-medal";
        if (rank === 3) return "fa-award";
        return "fa-user";
    }

    openUserRequests(userId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "User Requests",
            res_model: "llm.usage.log",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain: [["user_id", "=", userId]],
            context: {},
        });
    }
}

registry.category("actions").add("llm_top_users_dashboard", TopUsersDashboard);
