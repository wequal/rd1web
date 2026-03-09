(function (window) {
    let aiSummaryModalInstance = null;
    let aiSummaryPollInterval = null;

    function getElements() {
        return {
            modalElement: document.getElementById('aiSummaryModal'),
            spinner: document.getElementById('aiSummarySpinner'),
            successIcon: document.getElementById('aiSummarySuccess'),
            errorIcon: document.getElementById('aiSummaryError'),
            title: document.getElementById('aiSummaryModalTitle'),
            message: document.getElementById('aiSummaryModalMessage'),
            info: document.getElementById('aiSummaryModalInfo'),
            footer: document.getElementById('aiSummaryModalFooter'),
            progressContainer: document.getElementById('aiSummaryProgressContainer'),
            progressBar: document.getElementById('aiSummaryProgressBar'),
            progressText: document.getElementById('aiSummaryProgressText')
        };
    }

    function ensureModal() {
        const els = getElements();
        if (!els.modalElement) {
            console.error('AI Summary modal element not found in DOM.');
            return null;
        }

        if (typeof bootstrap === 'undefined') {
            console.error('Bootstrap is not loaded. AI Summary modal cannot be shown.');
            return null;
        }

        if (!aiSummaryModalInstance) {
            aiSummaryModalInstance = new bootstrap.Modal(els.modalElement, {
                backdrop: 'static',
                keyboard: false
            });

            els.modalElement.addEventListener('hidden.bs.modal', function () {
                if (aiSummaryPollInterval) {
                    clearInterval(aiSummaryPollInterval);
                    aiSummaryPollInterval = null;
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

        if (els.title) els.title.textContent = titleText || 'Generating AI Summary';
        if (els.message) els.message.textContent = messageText || 'Analyzing current folder logs...';
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

        const statusUrlBase = (options && options.statusUrlBase) || '/rma/generate-ai-summary-status/';
        const statusUrl = `${statusUrlBase}${taskId}/`;

        fetch(statusUrl)
            .then(response => response.json())
            .then(data => {
                if (!data.success) {
                    if (aiSummaryPollInterval) {
                        clearInterval(aiSummaryPollInterval);
                        aiSummaryPollInterval = null;
                    }
                    updateUiForStatus(els, 'failed', 0, data.error || 'Failed to check AI summary status');
                    return;
                }

                const status = data.status;
                const progress = typeof data.progress === 'number' ? data.progress : 0;
                const message = data.message || '';
                updateUiForStatus(els, status, progress, message);

                if (status === 'completed' || status === 'failed') {
                    if (aiSummaryPollInterval) {
                        clearInterval(aiSummaryPollInterval);
                        aiSummaryPollInterval = null;
                    }

                    if (status === 'completed') {
                        setTimeout(function () {
                            window.location.reload();
                        }, 2000);
                    }
                }
            })
            .catch(error => {
                console.error('Error checking AI summary status:', error);
                if (aiSummaryPollInterval) {
                    clearInterval(aiSummaryPollInterval);
                    aiSummaryPollInterval = null;
                }
                updateUiForStatus(els, 'failed', 0, error.message || 'Failed to check AI summary status');
            });
    }

    function startTask(taskId, options) {
        const els = ensureModal();
        if (!els) return;

        resetUi(els, options && options.title, options && options.message);
        if (aiSummaryModalInstance) {
            aiSummaryModalInstance.show();
        }

        if (aiSummaryPollInterval) {
            clearInterval(aiSummaryPollInterval);
            aiSummaryPollInterval = null;
        }

        pollStatus(taskId, options);
        aiSummaryPollInterval = setInterval(function () {
            pollStatus(taskId, options);
        }, 3000);
    }

    function getCsrfToken() {
        const cookies = document.cookie.split(';');
        for (let cookie of cookies) {
            const parts = cookie.trim().split('=');
            if (parts.length === 2 && parts[0] === 'csrftoken') {
                return decodeURIComponent(parts[1]);
            }
        }
        return '';
    }

    window.AiSummary = {
        startTask: startTask,
        getCsrfToken: getCsrfToken
    };
})(window);
