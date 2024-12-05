class ChatInterface {
    constructor() {
        this.messagesContainer = document.getElementById('messages');
        this.chatForm = document.getElementById('chat-form');
        this.userInput = document.getElementById('user-input');
        
        this.setupEventListeners();
        this.focusInput();
    }

    setupEventListeners() {
        this.chatForm.addEventListener('submit', (e) => this.handleSubmit(e));
    }

    focusInput() {
        this.userInput.focus();
    }

    scrollToBottom() {
        this.messagesContainer.scrollTop = this.messagesContainer.scrollHeight;
    }

    addMessage(content, isUser = false) {
        const messageDiv = document.createElement('div');
        messageDiv.className = 'flex items-start space-x-4';

        const avatar = document.createElement('div');
        avatar.className = `w-10 h-10 rounded-full ${isUser ? 'bg-gray-500' : 'bg-blue-500'} flex items-center justify-center flex-shrink-0`;
        
        const icon = document.createElement('svg');
        icon.className = 'w-6 h-6 text-white';
        icon.setAttribute('fill', 'none');
        icon.setAttribute('stroke', 'currentColor');
        icon.setAttribute('viewBox', '0 0 24 24');

        const path = document.createElement('path');
        path.setAttribute('stroke-linecap', 'round');
        path.setAttribute('stroke-linejoin', 'round');
        path.setAttribute('stroke-width', '2');
        
        if (isUser) {
            path.setAttribute('d', 'M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z');
        } else {
            path.setAttribute('d', 'M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z');
        }

        icon.appendChild(path);
        avatar.appendChild(icon);

        const bubble = document.createElement('div');
        bubble.className = `${isUser ? 'bg-blue-500 text-white' : 'bg-gray-100 text-gray-800'} rounded-lg p-4 max-w-3xl`;

        if (isUser) {
            // Si c'est un message utilisateur, c'est toujours du texte simple
            bubble.textContent = content;
        } else if (typeof content === 'object' && content.answer) {
            // Si c'est une réponse de l'API
            this.renderEmailResult(bubble, content);
        } else {
            // Pour les autres messages (comme les erreurs)
            bubble.textContent = content;
        }

        messageDiv.appendChild(avatar);
        messageDiv.appendChild(bubble);
        this.messagesContainer.appendChild(messageDiv);
        this.scrollToBottom();
    }

    renderEmailResult(container, result) {
        // Réponse principale
        const answerDiv = document.createElement('div');
        answerDiv.className = 'bg-blue-50 p-4 rounded-lg mb-4';
        answerDiv.textContent = result.answer;
        container.appendChild(answerDiv);

        if (result.relevant_emails && result.relevant_emails.length > 0) {
            // Titre des emails pertinents
            const emailsTitle = document.createElement('h3');
            emailsTitle.className = 'text-sm font-semibold text-gray-500 uppercase tracking-wider mb-4';
            emailsTitle.textContent = 'Emails pertinents';
            container.appendChild(emailsTitle);

            // Liste des emails
            result.relevant_emails.forEach(email => {
                const emailDiv = document.createElement('div');
                emailDiv.className = 'bg-white border border-gray-200 rounded-lg p-4 mb-4';

                // En-tête de l'email
                const headerDiv = document.createElement('div');
                headerDiv.className = 'flex justify-between items-start mb-3 pb-2 border-b';

                const senderDiv = document.createElement('div');
                const senderName = document.createElement('p');
                senderName.className = 'font-medium text-gray-900';
                senderName.textContent = email.sender.split('<')[0].trim();
                
                const subject = document.createElement('p');
                subject.className = 'text-gray-600';
                subject.textContent = email.subject;

                senderDiv.appendChild(senderName);
                senderDiv.appendChild(subject);

                const date = document.createElement('p');
                date.className = 'text-sm text-gray-500';
                date.textContent = new Date(email.date).toLocaleDateString('fr-FR');

                headerDiv.appendChild(senderDiv);
                headerDiv.appendChild(date);

                // Corps de l'email
                const bodyDiv = document.createElement('div');
                bodyDiv.className = 'text-gray-600 space-y-4';

                // Formater le contenu de l'email
                const formattedContent = this.formatEmailContent(email.body);
                formattedContent.forEach(paragraph => {
                    if (paragraph.type === 'text') {
                        const p = document.createElement('p');
                        p.textContent = paragraph.content;
                        bodyDiv.appendChild(p);
                    } else if (paragraph.type === 'list') {
                        const ul = document.createElement('ul');
                        ul.className = 'list-disc pl-4 space-y-1';
                        paragraph.items.forEach(item => {
                            const li = document.createElement('li');
                            li.textContent = item;
                            ul.appendChild(li);
                        });
                        bodyDiv.appendChild(ul);
                    } else if (paragraph.type === 'signature') {
                        const sig = document.createElement('div');
                        sig.className = 'text-gray-500 border-t pt-2 mt-4';
                        paragraph.lines.forEach(line => {
                            const p = document.createElement('p');
                            p.className = 'text-sm';
                            p.textContent = line;
                            sig.appendChild(p);
                        });
                        bodyDiv.appendChild(sig);
                    }
                });

                emailDiv.appendChild(headerDiv);
                emailDiv.appendChild(bodyDiv);
                container.appendChild(emailDiv);
            });
        }
    }

    formatEmailContent(rawBody) {
        // Supprime l'en-tête complet avec un regex plus précis
        const headerPattern = /De:.*\nObjet:.*\nDate:.*\n/;
        const body = rawBody.replace(headerPattern, '').trim();
        
        // Divise le contenu en lignes
        const lines = body.split('\n');
        const formattedContent = [];
        let currentList = null;
        let signature = [];
        let isSignature = false;

        lines.forEach((line, index) => {
            line = line.trim();
            
            // Ignore les lignes vides et les en-têtes redondants
            if (!line || line.startsWith('De:') || line.startsWith('Objet:') || line.startsWith('Date:')) return;

            // Détecte le début de la signature
            if (line.match(/^(Cordialement|Bien cordialement|À bientôt|Sincèrement|Regards|Best regards),?$/i)) {
                isSignature = true;
                signature.push(line);
                return;
            }

            // Ajoute les lignes à la signature
            if (isSignature) {
                signature.push(line);
                return;
            }

            // Gestion des listes à puces
            if (line.startsWith('•') || line.startsWith('*')) {
                if (!currentList) {
                    currentList = { type: 'list', items: [] };
                    formattedContent.push(currentList);
                }
                currentList.items.push(line.substring(1).trim());
                return;
            }

            // Si ce n'est pas une puce et qu'on avait une liste en cours
            if (currentList) {
                currentList = null;
            }

            // Texte normal
            formattedContent.push({
                type: 'text',
                content: line
            });
        });

        // Ajoute la signature si elle existe
        if (signature.length > 0) {
            formattedContent.push({
                type: 'signature',
                lines: signature
            });
        }

        return formattedContent;
    }



    addLoadingMessage() {
        const loadingDiv = document.createElement('div');
        loadingDiv.className = 'flex items-start space-x-4 loading-message';

        loadingDiv.innerHTML = `
            <div class="w-10 h-10 rounded-full bg-blue-500 flex items-center justify-center flex-shrink-0">
                <svg class="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z"/>
                </svg>
            </div>
            <div class="bg-gray-100 rounded-lg p-4 max-w-3xl">
                <div class="flex space-x-2">
                    <div class="w-3 h-3 bg-gray-400 rounded-full loading-dots"></div>
                    <div class="w-3 h-3 bg-gray-400 rounded-full loading-dots" style="animation-delay: 0.2s"></div>
                    <div class="w-3 h-3 bg-gray-400 rounded-full loading-dots" style="animation-delay: 0.4s"></div>
                </div>
            </div>
        `;

        this.messagesContainer.appendChild(loadingDiv);
        this.scrollToBottom();
        return loadingDiv;
    }

    removeLoadingMessage() {
        const loadingMessage = document.querySelector('.loading-message');
        if (loadingMessage) {
            loadingMessage.remove();
        }
    }


    async handleSubmit(e) {
        e.preventDefault();
        const question = this.userInput.value.trim();
        
        if (!question) return;

        // Ajouter le message de l'utilisateur
        this.addMessage(question, true);
        this.userInput.value = '';

        // Ajouter l'animation de chargement
        const loadingMessage = this.addLoadingMessage();

        try {
            const response = await fetch(`${settings.getServerUrl()}/api/v1/search`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ question }),
            });

            const result = await response.json();

            // Supprimer l'animation de chargement
            this.removeLoadingMessage();

            if (result.status === 'error') {
                this.addMessage('Désolé, une erreur est survenue. Veuillez réessayer.');
            } else {
                // Ajouter la réponse formatée
                this.addMessage(result, false);
            }
        } catch (error) {
            console.error('An error occurred while fetching the data:', error);
            this.removeLoadingMessage();
            this.addMessage('Désolé, une erreur de connexion est survenue. Veuillez vérifier que le serveur est bien lancé et que l\'URL du serveur est correcte dans les paramètres.');
        }
    }
}

// Initialize chat interface
const chat = new ChatInterface();