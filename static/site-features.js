/* Site entrance animation */

document.addEventListener('DOMContentLoaded', function() {
    // Create overlay for entrance animation
    const overlay = document.createElement('div');
    overlay.className = 'entrance-overlay';
    overlay.innerHTML = `
        <div class="entrance-content">
            <div class="brand-animation">
                <span class="brand-title-anim">Atelier Gourmand</span>
                <span class="brand-subtitle-anim">by OC · London</span>
            </div>
            <div class="loading-bar">
                <div class="loading-progress"></div>
            </div>
        </div>
    `;
    document.body.prepend(overlay);
    
    // Animate entrance
    setTimeout(() => {
        overlay.classList.add('fade-out');
        setTimeout(() => {
            overlay.remove();
            document.body.classList.add('entrance-complete');
        }, 800);
    }, 2000);
});
