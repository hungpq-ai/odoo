/** @odoo-module **/

import { LLMThreadHeader } from "@llm_thread/components/llm_thread_header/llm_thread_header";
import { patch } from "@web/core/utils/patch";
import { onWillStart } from "@odoo/owl";

/**
 * Patch LLMThreadHeader to add RAG/Collections functionality
 */
patch(LLMThreadHeader.prototype, {
    setup() {
        super.setup();
        // Add collections state
        this.state.collectionSearchQuery = "";
        this.state.collectionsLoaded = false;
        this.collections = [];

        // Load collections on component start
        onWillStart(async () => {
            await this.loadCollections();
        });
    },

    /**
     * Get current collections from thread
     */
    get currentCollections() {
        if (!this.hasActiveThread) return [];
        const collectionIds = this.activeThread.collection_ids || [];
        return collectionIds.filter(Boolean);
    },

    /**
     * Check if RAG is enabled
     */
    get ragEnabled() {
        if (!this.hasActiveThread) return false;
        return this.activeThread.rag_enabled || false;
    },

    /**
     * Get available collections (filtered by search)
     */
    get availableCollections() {
        let collections = this.collections || [];

        // Apply search filter if any
        if (this.state.collectionSearchQuery) {
            const query = this.state.collectionSearchQuery.toLowerCase();
            collections = collections.filter((c) =>
                c.name.toLowerCase().includes(query)
            );
        }

        return collections;
    },

    /**
     * Load collections from server
     */
    async loadCollections() {
        if (this.state.collectionsLoaded) return;

        try {
            const collections = await this.orm.searchRead(
                "llm.knowledge.collection",
                [],
                ["id", "name"],
                { limit: 100 }
            );
            this.collections = collections;
            this.state.collectionsLoaded = true;
        } catch (error) {
            console.error("Error loading collections:", error);
            this.collections = [];
        }
    },

    /**
     * Toggle collection selection
     * @param {Object} collection - Collection object to toggle
     */
    async toggleCollection(collection) {
        try {
            this.state.isLoadingUpdate = true;

            // Get current collection IDs
            const currentIds = (this.activeThread.collection_ids || []).map((c) =>
                typeof c === "object" ? c.id : c
            );

            const newIds = currentIds.includes(collection.id)
                ? currentIds.filter((id) => id !== collection.id)
                : [...currentIds, collection.id];

            // Also enable/disable RAG based on selection
            const ragEnabled = newIds.length > 0;

            // Update via ORM
            await this.orm.write("llm.thread", [this.activeThread.id], {
                collection_ids: [[6, 0, newIds]],
                rag_enabled: ragEnabled,
            });

            // Update local state
            this.activeThread.collection_ids = newIds;
            this.activeThread.rag_enabled = ragEnabled;

            // Reload thread data
            await this.activeThread.fetchData(["collection_ids", "rag_enabled"]);
        } catch (error) {
            this.notification.add(
                "Could not update collections. Please try again.",
                { type: "danger" }
            );
            console.error("Error updating collections:", error);
        } finally {
            this.state.isLoadingUpdate = false;
        }
    },

    /**
     * Check if a collection is selected
     * @param {Object} collection - Collection to check
     * @returns {Boolean}
     */
    isCollectionSelected(collection) {
        if (!this.hasActiveThread) return false;
        const ids = (this.activeThread.collection_ids || []).map((c) =>
            typeof c === "object" ? c.id : c
        );
        return ids.includes(collection.id);
    },

    /**
     * Handle collection search input
     * @param {Event} ev
     */
    onCollectionSearchInput(ev) {
        this.state.collectionSearchQuery = ev.target.value;
    },

    /**
     * Clear collection search
     */
    clearCollectionSearch() {
        this.state.collectionSearchQuery = "";
    },
});
