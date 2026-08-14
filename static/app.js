// Drag-and-Drop and XHR Upload JavaScript for LAN Share Pro

document.addEventListener('DOMContentLoaded', () => {
    const dropzone = document.getElementById('dropzone');
    const fileInput = document.getElementById('file-input');
    const progressList = document.getElementById('progress-list');

    if (!dropzone || !fileInput) return;

    // Prevent default browser drag open behavior for the body
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        document.body.addEventListener(eventName, (e) => e.preventDefault(), false);
    });

    // Visual drag over feedback on dropzone
    ['dragover', 'dragenter'].forEach(eventName => {
        dropzone.addEventListener(eventName, () => dropzone.classList.add('dragover'), false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        dropzone.addEventListener(eventName, () => dropzone.classList.remove('dragover'), false);
    });

    // Handle dropped files
    dropzone.addEventListener('drop', (e) => {
        const files = e.dataTransfer.files;
        if (files.length) uploadFiles(files);
    });
});

// Multi-file XHR Upload with live progress bars
function uploadFiles(files) {
    const progressList = document.getElementById('progress-list');
    let inFlight = files.length;

    Array.from(files).forEach(file => {
        const row = document.createElement('div');
        row.className = 'progress-row';
        row.innerHTML = `
            <div class="progress-row-header">
                <span>📄 ${file.name}</span>
                <span id="pct-${file.name}">0%</span>
            </div>
            <div class="progress-bar-bg">
                <div class="progress-bar-fill" id="bar-${file.name}"></div>
            </div>
        `;
        progressList.appendChild(row);

        const xhr = new XMLHttpRequest();
        const formData = new FormData();
        formData.append('files', file);

        // Update progress bar width dynamically
        xhr.upload.addEventListener('progress', (e) => {
            if (e.lengthComputable) {
                const pct = Math.round((e.loaded / e.total) * 100);
                const bar = document.getElementById(`bar-${file.name}`);
                const pctText = document.getElementById(`pct-${file.name}`);
                if (bar) bar.style.width = pct + '%';
                if (pctText) pctText.textContent = pct + '%';
            }
        });

        // Trigger on upload completion
        xhr.onload = function() {
            inFlight--;
            const pctText = document.getElementById(`pct-${file.name}`);
            if (pctText) pctText.textContent = 'Done ✓';

            if (inFlight === 0) {
                setTimeout(() => location.reload(), 600);
            }
        };

        xhr.open('POST', '/upload');
        xhr.send(formData);
    });
}

// Asynchronous File Deletion Request
function deleteFile(filename) {
    if (!confirm(`Delete "${filename}"?`)) return;

    fetch(`/files/${encodeURIComponent(filename)}/delete`, { method: 'POST' })
        .then(res => {
            if (res.ok) {
                const card = document.getElementById(`card-${filename}`);
                if (card) card.remove();
                location.reload();
            } else {
                alert('Failed to delete file.');
            }
        })
        .catch(err => {
            console.error(err);
            alert('Error connecting to server.');
        });
}
