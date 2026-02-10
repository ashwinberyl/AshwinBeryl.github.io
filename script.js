/* RECRUITER PORTFOLIO — INTERACTIONS */

document.addEventListener('DOMContentLoaded', () => {
    initThemeToggle();
    initScrollProgress();
    initRevealAnimations();
    initMetricCounters();
    initTerminalAnimation();
    initSmoothScroll();
    initNavHighlight();
    initContactForm();
});

// ---------- THEME TOGGLE ----------
function initThemeToggle() {
    const toggle = document.getElementById('theme-toggle');
    const html = document.documentElement;

    // Load saved preference
    const saved = localStorage.getItem('theme');
    if (saved) {
        html.setAttribute('data-theme', saved);
    }

    toggle.addEventListener('click', () => {
        const current = html.getAttribute('data-theme');
        const next = current === 'light' ? 'dark' : 'light';
        html.setAttribute('data-theme', next);
        localStorage.setItem('theme', next);
    });
}

// ---------- SCROLL PROGRESS BAR ----------
function initScrollProgress() {
    const bar = document.getElementById('progress-bar');
    window.addEventListener('scroll', () => {
        const h = document.documentElement.scrollHeight - window.innerHeight;
        bar.style.width = (window.scrollY / h * 100) + '%';
    });
}

// ---------- REVEAL ON SCROLL ----------
function initRevealAnimations() {
    const reveals = document.querySelectorAll('.reveal');
    const observer = new IntersectionObserver((entries) => {
        entries.forEach((entry, i) => {
            if (entry.isIntersecting) {
                // Stagger siblings
                const parent = entry.target.parentElement;
                const siblings = parent.querySelectorAll('.reveal');
                let delay = 0;
                siblings.forEach(sib => {
                    if (sib === entry.target) {
                        entry.target.style.transitionDelay = delay + 'ms';
                    }
                    delay += 100;
                });
                entry.target.classList.add('visible');
                observer.unobserve(entry.target);
            }
        });
    }, { threshold: 0.15 });

    reveals.forEach(el => observer.observe(el));
}

// ---------- METRIC COUNTERS ----------
function initMetricCounters() {
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                const numEl = entry.target.querySelector('.metric-number');
                if (!numEl) return;
                const target = parseFloat(numEl.dataset.target);
                animateValue(numEl, 0, target, 1800);
                observer.unobserve(entry.target);
            }
        });
    }, { threshold: 0.3 });

    document.querySelectorAll('.metric-card').forEach(card => observer.observe(card));
}

function animateValue(el, start, end, duration) {
    const isFloat = end % 1 !== 0;
    const startTime = performance.now();

    function update(currentTime) {
        const elapsed = currentTime - startTime;
        const progress = Math.min(elapsed / duration, 1);
        // Ease-out cubic
        const eased = 1 - Math.pow(1 - progress, 3);
        const current = start + (end - start) * eased;

        el.textContent = isFloat ? current.toFixed(1) : Math.floor(current);

        if (progress < 1) requestAnimationFrame(update);
    }
    requestAnimationFrame(update);
}

// ---------- TERMINAL ANIMATION ----------
function initTerminalAnimation() {
    const el = document.getElementById('terminal-text');
    if (!el) return;

    const lines = [
        '$ whoami',
        'ashwin.kalaichandran',
        '',
        '$ cat role.txt',
        'DevSecOps Platform Engineer',
        '8 years | Bengaluru, IN',
        '',
        '$ kubectl get pods --all-namespaces',
        'NAMESPACE   STATUS    RESTARTS',
        'platform    Running   0',
        'security    Running   0',
        'pipelines   Running   0',
        '',
        '$ echo $STATUS',
        'Ready for new challenges ✓',
    ];

    let lineIndex = 0;
    let charIndex = 0;
    let currentText = '';

    function type() {
        if (lineIndex >= lines.length) return;

        const line = lines[lineIndex];

        if (charIndex < line.length) {
            currentText += line[charIndex];
            el.textContent = currentText + '█';
            charIndex++;
            // Commands type faster
            const speed = line.startsWith('$') ? 40 : 20;
            setTimeout(type, speed);
        } else {
            currentText += '\n';
            el.textContent = currentText + '█';
            charIndex = 0;
            lineIndex++;
            // Pause between lines
            const pause = lines[lineIndex - 1].startsWith('$') ? 400 : 80;
            setTimeout(type, pause);
        }
    }

    // Start after hero animation
    setTimeout(type, 1200);
}

// ---------- SMOOTH SCROLL ----------
function initSmoothScroll() {
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', (e) => {
            e.preventDefault();
            const target = document.querySelector(anchor.getAttribute('href'));
            if (target) {
                window.scrollTo({
                    top: target.offsetTop - 80,
                    behavior: 'smooth'
                });
            }
        });
    });
}

// ---------- NAV ACTIVE HIGHLIGHT ----------
function initNavHighlight() {
    const sections = document.querySelectorAll('section[id]');
    const links = document.querySelectorAll('.nav-links a');

    window.addEventListener('scroll', () => {
        let current = '';
        sections.forEach(section => {
            const top = section.offsetTop - 150;
            if (window.scrollY >= top) {
                current = section.getAttribute('id');
            }
        });

        links.forEach(link => {
            link.style.color = '';
            if (link.getAttribute('href') === `#${current}`) {
                link.style.color = getComputedStyle(document.documentElement).getPropertyValue('--text').trim();
            }
        });
    });
}

// ---------- CONTACT FORM ----------
function initContactForm() {
    const form = document.getElementById('contact-form');
    if (!form) return;

    form.addEventListener('submit', async (e) => {
        e.preventDefault();

        const btn = form.querySelector('.send-btn');
        const sendText = btn.querySelector('.send-text');
        const sendLoading = btn.querySelector('.send-loading');

        // Loading state
        btn.disabled = true;
        sendText.style.display = 'none';
        sendLoading.style.display = 'inline';

        try {
            const response = await fetch(form.action, {
                method: 'POST',
                body: new FormData(form),
                headers: { 'Accept': 'application/json' }
            });

            if (response.ok) {
                form.style.display = 'none';
                document.getElementById('form-success').style.display = 'block';
            } else {
                throw new Error('Form submission failed');
            }
        } catch (err) {
            // Fallback: open mailto
            const name = form.querySelector('#name').value;
            const email = form.querySelector('#email').value;
            const message = form.querySelector('#message').value;
            const subject = encodeURIComponent('Portfolio Contact from ' + name);
            const body = encodeURIComponent(`From: ${name} (${email})\n\n${message}`);
            window.open(`mailto:ashwinberyl@gmail.com?subject=${subject}&body=${body}`);

            btn.disabled = false;
            sendText.style.display = 'inline';
            sendLoading.style.display = 'none';
        }
    });
}
