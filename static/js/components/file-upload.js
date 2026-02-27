/**
 * File upload component for Alpine.js
 *
 * Usage:
 *   <div x-data="fileUpload()" @dragover.prevent="dragOver = true"
 *        @dragleave="dragOver = false" @drop.prevent="handleDrop($event)">
 *     ...
 *   </div>
 */
function fileUpload() {
    return {
        file: null,
        fileName: '',
        fileSize: '',
        dragOver: false,
        uploading: false,
        uploadProgress: 0,

        handleDrop(event) {
            this.dragOver = false;
            const files = event.dataTransfer.files;
            if (files.length > 0 && files[0].type === 'application/pdf') {
                this.selectFile(files[0]);
            }
        },

        handleFileInput(event) {
            if (event.target.files.length > 0) {
                this.selectFile(event.target.files[0]);
            }
        },

        selectFile(file) {
            this.file = file;
            this.fileName = file.name;
            this.fileSize = this.formatSize(file.size);
        },

        clear() {
            this.file = null;
            this.fileName = '';
            this.fileSize = '';
            this.uploadProgress = 0;
        },

        async upload() {
            if (!this.file) return null;
            this.uploading = true;
            try {
                const result = await api.uploadFile(this.file, (progress) => {
                    this.uploadProgress = progress;
                });
                return result;
            } finally {
                this.uploading = false;
            }
        },

        formatSize(bytes) {
            if (bytes === 0) return '0 Bytes';
            const k = 1024;
            const sizes = ['Bytes', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
        },
    };
}
