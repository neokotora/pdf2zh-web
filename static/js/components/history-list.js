/**
 * History list component for Alpine.js
 *
 * Usage:
 *   <div x-data="historyList()" x-init="load()">
 *     <template x-for="item in items" :key="item.task_id">
 *       ...
 *     </template>
 *   </div>
 */
function historyList() {
    return {
        items: [],
        loading: false,

        async load() {
            this.loading = true;
            try {
                const response = await api.getTranslationHistory();
                this.items = response.history || [];
            } catch (error) {
                console.error('Error loading history:', error);
            } finally {
                this.loading = false;
            }
        },

        async deleteItem(taskId) {
            if (!confirm(i18n.t('upload.history.delete.confirm'))) return;
            try {
                await api.deleteHistoryItem(taskId);
                this.items = this.items.filter(i => i.task_id !== taskId);
                showAlert(i18n.t('upload.history.delete.success'), 'success');
            } catch (error) {
                showAlert(i18n.t('upload.history.delete.failed') + error.message, 'error');
            }
        },

        getDisplayName(item) {
            let name = item.original_filename || item.filename || 'Untitled';
            if (name.includes('_')) {
                const parts = name.split('_');
                if (parts[0].includes('-') && parts[0].length > 20) {
                    name = parts.slice(1).join('_');
                }
            }
            return name || 'Untitled';
        },

        getStatusColor(status) {
            if (status === 'completed') return 'var(--accent-success)';
            if (status === 'failed') return 'var(--accent-error)';
            return 'var(--accent-warning)';
        },

        formatDate(dateString) {
            return new Date(dateString).toLocaleString();
        },
    };
}
