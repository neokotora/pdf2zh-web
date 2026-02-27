/**
 * Toast notification component for Alpine.js
 *
 * Usage:
 *   <div x-data="toastManager()" @show-toast.window="addToast($event.detail)">
 *     <template x-for="toast in toasts" :key="toast.id">
 *       <div :class="`alert alert-${toast.type}`" x-text="toast.message"
 *            x-transition x-show="toast.visible"></div>
 *     </template>
 *   </div>
 *
 *   // Trigger from anywhere:
 *   window.dispatchEvent(new CustomEvent('show-toast', {
 *     detail: { message: 'Success!', type: 'success' }
 *   }));
 */
function toastManager() {
    return {
        toasts: [],
        nextId: 0,

        addToast({ message, type = 'info', duration = 3000 }) {
            const id = this.nextId++;
            const toast = { id, message, type, visible: true };
            this.toasts.push(toast);

            setTimeout(() => {
                toast.visible = false;
                setTimeout(() => {
                    this.toasts = this.toasts.filter(t => t.id !== id);
                }, 300);
            }, duration);
        },
    };
}
