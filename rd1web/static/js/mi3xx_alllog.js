(function (window) {
    let mi3xxModalInstance = null;
    let mi3xxPollInterval = null;

    function getElements() {
        return {
            modalElement: document.getElementById('mi3xxAllLogModal'),
            spinner: document.getElementById('mi3xxSpinner'),
            successIcon: document.getElementById('mi3xxSuccess'),
            errorIcon: document.getElementById('mi3xxError'),
            title: document.getElementById('mi3xxModalTitle'),
            message: document.getElementById('mi3xxModalMessage'),
            info: document.getElementById('mi3xxModalInfo'),
            footer: document.getElementById('mi3xxModalFooter'),
            progressContainer: document.getElementById('mi3xxProgressContainer'),
            progressBar: document.getElementById('mi3xxProgressBar'),
            progressText: document.getElementById('mi3xxProgressText')
        };
    }

    function ensureModal() {
        const els = getElements();
        if (!els.modalElement) {
            console.error('MI3XX All Log modal element not found in DOM.');
            return null;
        }

        if (typeof bootstrap === 'undefined') {
            console.error('Bootstrap is not loaded. MI3XX All Log modal cannot be shown.');
            return null;
        }

        if (!mi3xxModalInstance) {
            mi3xxModalInstance = new bootstrap.Modal(els.modalElement, {
                backdrop: 'static',
                keyboard: false
            });

            // Clean up polling when modal is hidden
            els.modalElement.addEventListener('hidden.bs.modal', function () {
                if (mi3xxPollInterval) {
                    clearInterval(mi3xxPollInterval);
                    mi3xxPollInterval = null;
                }
            });
        }

        return els;
    }

    function resetUi(els, titleText, messageText) {
        if (!els) return;

        if (els.spinner) els.spinner.classList.remove('d-none');
        if (els.successIcon) els.successIcon.classList.add('d-none');
        if (els.errorIcon) els.errorIcon.classList.add('d-none');
        if (els.footer) els.footer.classList.add('d-none');
        if (els.progressContainer) els.progressContainer.classList.remove('d-none');

        if (els.title) els.title.textContent = titleText || 'Collecting MI3XX ALL LOG';
        if (els.message) els.message.textContent = messageText || 'Initiating log collection from BMC...';
        if (els.info) els.info.textContent = '0%';

        if (els.progressBar) {
            els.progressBar.style.width = '0%';
            els.progressBar.setAttribute('aria-valuenow', '0');
        }
        if (els.progressText) {
            els.progressText.textContent = '0%';
        }
    }

    function updateUiForStatus(els, status, progress, message) {
        if (!els) return;

        if (typeof progress === 'number') {
            const clamped = Math.max(0, Math.min(100, progress));
            if (els.progressBar) {
                els.progressBar.style.width = clamped + '%';
                els.progressBar.setAttribute('aria-valuenow', String(clamped));
            }
            if (els.progressText) {
                els.progressText.textContent = clamped + '%';
            }
            if (els.info) {
                els.info.textContent = clamped + '%';
            }
        }

        if (els.message && message) {
            els.message.textContent = message;
        }

        if (status === 'completed') {
            if (els.spinner) els.spinner.classList.add('d-none');
            if (els.successIcon) els.successIcon.classList.remove('d-none');
            if (els.footer) els.footer.classList.remove('d-none');
        } else if (status === 'failed') {
            if (els.spinner) els.spinner.classList.add('d-none');
            if (els.errorIcon) els.errorIcon.classList.remove('d-none');
            if (els.footer) els.footer.classList.remove('d-none');
        }
    }

    function pollStatus(taskId, options) {
        const els = getElements();
        if (!els) return;

        const statusUrl = `/rma/collect-mi3xx-alllog-status/${taskId}/`;

        fetch(statusUrl)
            .then(response => response.json())
            .then(data => {
                if (!data.success) {
                    // Stop polling on error
                    if (mi3xxPollInterval) {
                        clearInterval(mi3xxPollInterval);
                        mi3xxPollInterval = null;
                    }

                    updateUiForStatus(els, 'failed', 0, data.error || 'Failed to check status');
                    if (els.info) {
                        els.info.textContent = 'Please try again';
                    }
                    return;
                }

                const status = data.status;
                const progress = typeof data.progress === 'number' ? data.progress : 0;
                const message = data.message || '';

                updateUiForStatus(els, status, progress, message);

                if (status === 'completed' || status === 'failed') {
                    if (mi3xxPollInterval) {
                        clearInterval(mi3xxPollInterval);
                        mi3xxPollInterval = null;
                    }

                    if (status === 'completed') {
                        // On success: either redirect or reload depending on options
                        const redirectUrl = options && options.redirectUrl;
                        const reloadOnSuccess = options && options.reloadOnSuccess;

                        if (redirectUrl) {
                            setTimeout(() => {
                                window.location.href = redirectUrl;
                            }, 3000);
                        } else if (reloadOnSuccess) {
                            setTimeout(() => {
                                window.location.reload();
                            }, 3000);
                        }
                    }
                }
            })
            .catch(error => {
                console.error('Error checking MI3XX status:', error);
                if (mi3xxPollInterval) {
                    clearInterval(mi3xxPollInterval);
                    mi3xxPollInterval = null;
                }

                updateUiForStatus(els, 'failed', 0, 'Failed to check status');
                if (els.info) {
                    els.info.textContent = error.message || 'Connection error';
                }
            });
    }

    function startTask(taskId, options) {
        const els = ensureModal();
        if (!els) {
            return;
        }

        // Reset UI and show modal
        resetUi(els, options && options.title, options && options.message);
        if (mi3xxModalInstance) {
            mi3xxModalInstance.show();
        }

        // Clear any existing polling interval
        if (mi3xxPollInterval) {
            clearInterval(mi3xxPollInterval);
            mi3xxPollInterval = null;
        }

        // Start polling immediately, then at regular intervals
        pollStatus(taskId, options);
        mi3xxPollInterval = setInterval(function () {
            pollStatus(taskId, options);
        }, 3000);
    }

    function getCsrfToken() {
        const cookies = document.cookie.split(';');
        for (let cookie of cookies) {
            const parts = cookie.trim().split('=');
            if (parts.length === 2) {
                const name = parts[0];
                const value = parts[1];
                if (name === 'csrftoken') {
                    return decodeURIComponent(value);
                }
            }
        }
        return '';
    }

    window.Mi3xxAllLog = {
        startTask: startTask,
        getCsrfToken: getCsrfToken
    };
})(window);


