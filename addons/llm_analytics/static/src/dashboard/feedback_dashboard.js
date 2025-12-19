/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { formatFloat, formatInteger } from "@web/views/fields/formatters";

class FeedbackDashboard extends Component {
    static template = "llm_analytics.FeedbackDashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");

        this.state = useState({
            loading: true,
            period: "month",
            stats: {
                total_feedback: 0,
                total_likes: 0,
                total_dislikes: 0,
                satisfaction_rate: 0,
            },
            byModel: [],
            byUser: [],
            recent: [],
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
                "get_feedback_data",
                [this.state.period]
            );
            this.state.stats = data.stats;
            this.state.byModel = data.by_model;
            this.state.byUser = data.by_user;
            this.state.recent = data.recent;
        } catch (error) {
            console.error("Failed to load feedback data:", error);
        }
        this.state.loading = false;
    }

    async onPeriodChange(period) {
        this.state.period = period;
        await this.loadData();
    }

    formatNumber(value) {
        return formatInteger(value || 0);
    }

    formatPercent(value) {
        return formatFloat(value || 0, { digits: [0, 1] }) + "%";
    }

    openFeedback(feedback) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: feedback === "like" ? "Liked Responses" : "Disliked Responses",
            res_model: "llm.usage.log",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain: [["feedback", "=", feedback]],
            context: {},
        });
    }

    openUserFeedback(userId, feedback) {
        const domain = [["user_id", "=", userId]];
        if (feedback) {
            domain.push(["feedback", "=", feedback]);
        } else {
            domain.push(["feedback", "!=", false]);
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "User Feedback",
            res_model: "llm.usage.log",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain: domain,
            context: {},
        });
    }
}

registry.category("actions").add("llm_feedback_dashboard", FeedbackDashboard);
