class Settings {
    constructor() {
        this.serverUrl = localStorage.getItem('serverUrl') || 'http://localhost:5000';
        this.setupEventListeners();
        this.initializeSettings();
    }

    setupEventListeners() {
        // Modal elements
        this.modal = document.getElementById('settings-modal');
        this.settingsButton = document.getElementById('settings-button');
        this.cancelButton = document.getElementById('cancel-settings');
        this.saveButton = document.getElementById('save-settings');
        this.serverUrlInput = document.getElementById('server-url');

        // Event listeners
        this.settingsButton.addEventListener('click', () => this.openModal());
        this.cancelButton.addEventListener('click', () => this.closeModal());
        this.saveButton.addEventListener('click', () => this.saveSettings());

        // Close modal when clicking outside
        this.modal.addEventListener('click', (e) => {
            if (e.target === this.modal) {
                this.closeModal();
            }
        });
    }

    initializeSettings() {
        this.serverUrlInput.value = this.serverUrl;
    }

    openModal() {
        this.modal.classList.remove('hidden');
        this.modal.classList.add('modal-fade-enter');
        this.serverUrlInput.value = this.serverUrl;
    }

    closeModal() {
        this.modal.classList.add('hidden');
    }

    saveSettings() {
        const newServerUrl = this.serverUrlInput.value.trim();
        
        if (newServerUrl) {
            this.serverUrl = newServerUrl;
            localStorage.setItem('serverUrl', newServerUrl);
            this.closeModal();
            
            // Display success message
            const messagesContainer = document.getElementById('messages');
            const successMessage = document.createElement('div');
            successMessage.className = 'text-center text-sm text-green-600 mb-4';
            successMessage.textContent = 'Paramètres sauvegardés avec succès';
            messagesContainer.appendChild(successMessage);
            
            setTimeout(() => {
                successMessage.remove();
            }, 3000);
        }
    }

    getServerUrl() {
        return this.serverUrl;
    }
}

// Initialize settings
const settings = new Settings();