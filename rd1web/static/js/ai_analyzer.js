(function (window) {
    let aiAnalyzerModalInstance = null;
    let aiAnalyzerPollInterval = null;

    function byId(id) {
        return document.getElementById(id);
    }

    function getModalElements() {
        return {
            modalElement: byId('aiAnalyzerModal'),
            spinner: byId('aiAnalyzerSpinner'),
            successIcon: byId('aiAnalyzerSuccess'),
            errorIcon: byId('aiAnalyzerError'),
            title: byId('aiAnalyzerModalTitle'),
            message: byId('aiAnalyzerModalMessage'),
            info: byId('aiAnalyzerModalInfo'),
            footer: byId('aiAnalyzerModalFooter'),
            progressContainer: byId('aiAnalyzerProgressContainer'),
            progressBar: byId('aiAnalyzerProgressBar'),
            progressText: byId('aiAnalyzerProgressText')
        };
    }

    function ensureModal() {
        const els = getModalElements();
        if (!els.modalElement || typeof bootstrap === 'undefined') {
            return null;
        }

        if (!aiAnalyzerModalInstance) {
            aiAnalyzerModalInstance = new bootstrap.Modal(els.modalElement, {
                backdrop: 'static',
                keyboard: false
            });
            els.modalElement.addEventListener('hidden.bs.modal', function () {
                if (aiAnalyzerPollInterval) {
                    clearInterval(aiAnalyzerPollInterval);
                    aiAnalyzerPollInterval = null;
                }
            });
        }
        return els;
    }

    function updateProgress(els, progress) {
        const value = Math.max(0, Math.min(100, Number(progress) || 0));
        if (els.progressBar) {
            els.progressBar.style.width = value + '%';
            els.progressBar.setAttribute('aria-valuenow', String(value));
        }
        if (els.progressText) {
            els.progressText.textContent = value + '%';
        }
        if (els.info) {
            els.info.textContent = value + '%';
        }
    }

    function setStatusState(els, state, message, progress) {
        updateProgress(els, progress);
        if (els.message && message) {
            els.message.textContent = message;
        }

        if (state === 'completed') {
            if (els.spinner) els.spinner.classList.add('d-none');
            if (els.successIcon) els.successIcon.classList.remove('d-none');
            if (els.errorIcon) els.errorIcon.classList.add('d-none');
            if (els.footer) els.footer.classList.remove('d-none');
        } else if (state === 'failed') {
            if (els.spinner) els.spinner.classList.add('d-none');
            if (els.errorIcon) els.errorIcon.classList.remove('d-none');
            if (els.successIcon) els.successIcon.classList.add('d-none');
            if (els.footer) els.footer.classList.remove('d-none');
        } else {
            if (els.spinner) els.spinner.classList.remove('d-none');
            if (els.errorIcon) els.errorIcon.classList.add('d-none');
            if (els.successIcon) els.successIcon.classList.add('d-none');
            if (els.footer) els.footer.classList.add('d-none');
        }
    }

    function getCsrfToken() {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const parts = cookies[i].trim().split('=');
            if (parts.length === 2 && parts[0] === 'csrftoken') {
                return decodeURIComponent(parts[1]);
            }
        }
        return '';
    }

    function pollStatus(taskId, config) {
        const els = getModalElements();
        const statusUrl = config.statusUrlBase + taskId + '/';
        fetch(statusUrl)
            .then(function (response) { return response.json(); })
            .then(function (data) {
                if (!data.success) {
                    throw new Error(data.error || 'Failed to check task status');
                }

                setStatusState(els, data.status, data.message, data.progress);
                if (data.status === 'completed' || data.status === 'failed') {
                    if (aiAnalyzerPollInterval) {
                        clearInterval(aiAnalyzerPollInterval);
                        aiAnalyzerPollInterval = null;
                    }
                }

                if (data.status === 'completed') {
                    const report = byId(config.reportContainerId);
                    const resultCard = byId(config.resultCardId);
                    if (report) {
                        report.innerHTML = data.report_html || '';
                    }
                    if (resultCard) {
                        resultCard.classList.remove('d-none');
                    }
                } else if (data.status === 'failed') {
                    showError(config.errorId, data.error || data.message || 'AI analysis failed.');
                }
            })
            .catch(function (error) {
                if (aiAnalyzerPollInterval) {
                    clearInterval(aiAnalyzerPollInterval);
                    aiAnalyzerPollInterval = null;
                }
                setStatusState(els, 'failed', error.message || 'Failed to check status', 0);
                showError(config.errorId, error.message || 'Failed to check status');
            });
    }

    function showError(errorId, message) {
        const el = byId(errorId);
        if (!el) return;
        el.textContent = message;
        el.classList.remove('d-none');
    }

    function clearError(errorId) {
        const el = byId(errorId);
        if (!el) return;
        el.textContent = '';
        el.classList.add('d-none');
    }

    function validateLinks(form) {
        const rburn = (form.querySelector('[name="rburn_link"]').value || '').trim();
        const cburn = (form.querySelector('[name="cburn_link"]').value || '').trim();
        if (!rburn && !cburn) {
            return 'Please provide either Rburn link or Cburn link.';
        }
        if (rburn && cburn) {
            return 'Please provide only one link: Rburn or Cburn.';
        }
        return '';
    }

    function init(config) {
        const form = byId(config.formId);
        const submitBtn = byId(config.submitButtonId);
        if (!form || !submitBtn) {
            return;
        }

        form.addEventListener('submit', function (event) {
            event.preventDefault();
            clearError(config.errorId);

            const validationError = validateLinks(form);
            if (validationError) {
                showError(config.errorId, validationError);
                return;
            }

            const report = byId(config.reportContainerId);
            const resultCard = byId(config.resultCardId);
            if (report) report.innerHTML = '';
            if (resultCard) resultCard.classList.add('d-none');

            submitBtn.disabled = true;
            submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>Analyzing...';

            const modalEls = ensureModal();
            if (modalEls && aiAnalyzerModalInstance) {
                setStatusState(modalEls, 'processing', 'OpenClaw is analyzing the submitted URL...', 0);
                aiAnalyzerModalInstance.show();
            }

            const formData = new FormData(form);
            fetch(config.runUrl, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': getCsrfToken()
                },
                body: formData
            })
                .then(function (response) { return response.json(); })
                .then(function (data) {
                    if (!data.success || !data.task_id) {
                        throw new Error(data.error || 'Failed to start AI analysis.');
                    }
                    pollStatus(data.task_id, config);
                    aiAnalyzerPollInterval = setInterval(function () {
                        pollStatus(data.task_id, config);
                    }, 3000);
                })
                .catch(function (error) {
                    showError(config.errorId, error.message || 'Failed to start AI analysis.');
                    const els = getModalElements();
                    if (els) {
                        setStatusState(els, 'failed', error.message || 'Failed to start AI analysis.', 0);
                    }
                })
                .finally(function () {
                    submitBtn.disabled = false;
                    submitBtn.innerHTML = '<i class="fas fa-robot me-1"></i>Analyze';
                });
        });
    }

    window.AiAnalyzer = {
        init: init
    };
})(window);
