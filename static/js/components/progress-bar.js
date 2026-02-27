/**
 * Progress bar component for Alpine.js
 *
 * Usage:
 *   <div x-data="progressBar()" x-init="start(taskId)">
 *     <div class="progress-bar">
 *       <div class="progress-fill" :style="`width: ${progress}%`"></div>
 *     </div>
 *     <p x-text="message"></p>
 *   </div>
 */
function progressBar() {
    return {
        progress: 0,
        message: 'Initializing...',
        status: 'queued',
        eventSource: null,

        start(taskId) {
            if (!taskId) return;
            this.connect(taskId);
        },

        connect(taskId) {
            this.cleanup();
            try {
                this.eventSource = api.streamTranslationProgress(taskId, {
                    onProgress: (data) => {
                        this.progress = data.progress || 0;
                        this.message = data.message || 'Processing...';
                        this.status = data.status || 'processing';
                    },
                    onComplete: (data) => {
                        this.progress = 100;
                        this.message = data.message || 'Translation completed';
                        this.status = 'completed';
                        this.$dispatch('translation-complete', data);
                        this.eventSource = null;
                    },
                    onError: (data) => {
                        this.message = data.message || 'Translation failed';
                        this.status = 'failed';
                        this.$dispatch('translation-error', data);
                        this.eventSource = null;
                    },
                });
            } catch (e) {
                console.warn('SSE unavailable, use polling fallback');
            }
        },

        cleanup() {
            if (this.eventSource) {
                this.eventSource.close();
                this.eventSource = null;
            }
        },

        destroy() {
            this.cleanup();
        },
    };
}
