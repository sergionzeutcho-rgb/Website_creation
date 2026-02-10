/* Site entrance animation (configurable from admin) */

document.addEventListener('DOMContentLoaded', function() {
    const cfg = window.entranceConfig || {};
    if (cfg.enabled === false) {
        document.body.classList.add('entrance-complete');
        return;
    }

    const duration = Math.max(300, parseInt(cfg.duration_ms, 10) || 2000);
    const fade = Math.max(200, parseInt(cfg.fade_ms, 10) || 800);

    const overlay = document.createElement('div');
    overlay.className = 'entrance-overlay';
    overlay.style.transitionDuration = `${fade}ms`;

    const content = document.createElement('div');
    content.className = 'entrance-content';

    if (cfg.logo_url) {
        const logo = document.createElement('img');
        logo.className = 'entrance-logo';
        logo.src = cfg.logo_url;
        logo.alt = 'Logo';
        content.appendChild(logo);
    }

    const brand = document.createElement('div');
    brand.className = 'brand-animation';

    const title = document.createElement('span');
    title.className = 'brand-title-anim';
    title.textContent = cfg.title || 'Atelier Gourmand';
    brand.appendChild(title);

    if (cfg.subtitle) {
        const subtitle = document.createElement('span');
        subtitle.className = 'brand-subtitle-anim';
        subtitle.textContent = cfg.subtitle;
        brand.appendChild(subtitle);
    }

    content.appendChild(brand);

    if (cfg.description) {
        const desc = document.createElement('p');
        desc.className = 'brand-desc-anim';
        desc.textContent = cfg.description;
        content.appendChild(desc);
    }

    if (cfg.extra_text) {
        const extra = document.createElement('p');
        extra.className = 'brand-extra-anim';
        extra.textContent = cfg.extra_text;
        content.appendChild(extra);
    }

    const bar = document.createElement('div');
    bar.className = 'loading-bar';
    const progress = document.createElement('div');
    progress.className = 'loading-progress';
    progress.style.animationDuration = `${duration}ms`;
    bar.appendChild(progress);
    content.appendChild(bar);

    overlay.appendChild(content);
    document.body.prepend(overlay);
    
    // Animate entrance
    setTimeout(() => {
        overlay.classList.add('fade-out');
        setTimeout(() => {
            overlay.remove();
            document.body.classList.add('entrance-complete');
        }, fade);
    }, duration);
});
