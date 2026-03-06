/**
 * Language Switcher - Dynamic Injection  
 * Adds EN/ES buttons to header after page loads
 */
(function() {
    'use strict';

    // Wait for DOM to be ready
    function init() {
        // Find the header element (where Refresh and Run Cycle buttons are)
        const header = document.querySelector('.header, header, [class*="header"]');
        const lastUpdate = document.getElementById('last-update');
        
        if (!lastUpdate) {
            console.warn('Last update element not found, retrying...');
            setTimeout(init, 500);
            return;
        }

        // Create the language switcher container
        const switcher = document.createElement('div');
        switcher.className = 'lang-switcher';
        switcher.style.cssText = `
            position: fixed;
            top: 80px;
            right: 30px;
            display: flex;
            gap: 12px;
            z-index: 1000;
        `;

        // Create EN button
        const enBtn = document.createElement('span');
        enBtn.className = 'lang-flag';
        enBtn.setAttribute('data-lang', 'en');
        enBtn.textContent = 'EN';
        enBtn.title = 'English';
        enBtn.style.cssText = `
            display: inline-block;
            font-size: 16px;
            font-weight: 700;
            cursor: pointer;
            padding: 8px 16px;
            background: rgba(59, 130, 246, 0.2);
            border: 2px solid rgba(59, 130, 246, 0.5);
            border-radius: 8px;
            color: #60a5fa;
            transition: all 0.2s ease;
            user-select: none;
            box-shadow: 0 2px 8px rgba(0,0,0,0.3);
        `;

        // Create ES button
        const esBtn = document.createElement('span');
        esBtn.className = 'lang-flag';
        esBtn.setAttribute('data-lang', 'es');
        esBtn.textContent = 'ES';
        esBtn.title = 'Español';
        esBtn.style.cssText = enBtn.style.cssText;

        // Add hover effects
        [enBtn, esBtn].forEach(btn => {
            btn.addEventListener('mouseenter', function() {
                this.style.background = 'rgba(59, 130, 246, 0.4)';
                this.style.borderColor = '#60a5fa';
                this.style.color = '#93c5fd';
                this.style.transform = 'scale(1.05)';
            });

            btn.addEventListener('mouseleave', function() {
                // Check if active
                const currentLang = localStorage.getItem('language') || 'en';
                if (this.getAttribute('data-lang') === currentLang) {
                    this.style.background = '#3b82f6';
                    this.style.borderColor = '#3b82f6';
                    this.style.color = 'white';
                } else {
                    this.style.background = 'rgba(59, 130, 246, 0.2)';
                    this.style.borderColor = 'rgba(59, 130, 246, 0.5)';
                    this.style.color = '#60a5fa';
                }
                this.style.transform = 'scale(1)';
            });

            // Click handler
            btn.addEventListener('click', function() {
                const lang = this.getAttribute('data-lang');
                localStorage.setItem('language', lang);
                location.reload();
            });
        });

        // Set active state
        function updateActiveState() {
            const currentLang = localStorage.getItem('language') || 'en';
            [enBtn, esBtn].forEach(btn => {
                if (btn.getAttribute('data-lang') === currentLang) {
                    btn.style.background = '#3b82f6';
                    btn.style.borderColor = '#3b82f6';
                    btn.style.color = 'white';
                } else {
                    btn.style.background = 'rgba(59, 130, 246, 0.2)';
                    btn.style.borderColor = 'rgba(59, 130, 246, 0.5)';
                    btn.style.color = '#60a5fa';
                }
            });
        }

        // Append buttons to switcher
        switcher.appendChild(enBtn);
        switcher.appendChild(esBtn);

        // Append to body so it's fixed positioned
        document.body.appendChild(switcher);

        // Set initial active state
        updateActiveState();

        console.log('✅ Language switcher buttons injected successfully!');
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
