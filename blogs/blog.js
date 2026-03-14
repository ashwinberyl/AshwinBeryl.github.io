/* BLOG — Tree Navigation, Markdown Rendering, Hash Routing, Search */

document.addEventListener('DOMContentLoaded', () => {
    initBlogTheme();
    initScrollProgress();
    initSidebar();
    loadBlogIndex();
    initMobileNav();
});

// ---------- THEME ----------
function initBlogTheme() {
    const toggle = document.getElementById('theme-toggle');
    const html = document.documentElement;

    const saved = localStorage.getItem('theme');
    if (saved === 'dark') {
        html.setAttribute('data-theme', 'dark');
    }
    updateHljsTheme();

    toggle.addEventListener('click', () => {
        const isDark = html.getAttribute('data-theme') === 'dark';
        if (isDark) {
            html.removeAttribute('data-theme');
            localStorage.setItem('theme', 'light');
        } else {
            html.setAttribute('data-theme', 'dark');
            localStorage.setItem('theme', 'dark');
        }
        updateHljsTheme();
    });
}

function updateHljsTheme() {
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    const darkSheet = document.getElementById('hljs-dark-theme');
    const lightSheet = document.getElementById('hljs-light-theme');
    if (darkSheet) darkSheet.disabled = !isDark;
    if (lightSheet) lightSheet.disabled = isDark;
}

// ---------- SCROLL PROGRESS ----------
function initScrollProgress() {
    const bar = document.getElementById('progress-bar');
    if (!bar) return;
    window.addEventListener('scroll', () => {
        const h = document.documentElement.scrollHeight - window.innerHeight;
        bar.style.width = h > 0 ? (window.scrollY / h * 100) + '%' : '0%';
    });
}

// ---------- MOBILE SIDEBAR ----------
function initMobileNav() {
    const toggle = document.getElementById('sidebar-toggle');
    const sidebar = document.getElementById('blog-sidebar');

    // Create overlay
    const overlay = document.createElement('div');
    overlay.className = 'sidebar-overlay';
    document.body.appendChild(overlay);

    function openSidebar() {
        sidebar.classList.add('open');
        overlay.classList.add('active');
        toggle.classList.add('active');
    }

    function closeSidebar() {
        sidebar.classList.remove('open');
        overlay.classList.remove('active');
        toggle.classList.remove('active');
    }

    toggle.addEventListener('click', () => {
        if (sidebar.classList.contains('open')) {
            closeSidebar();
        } else {
            openSidebar();
        }
    });

    overlay.addEventListener('click', closeSidebar);

    // Close sidebar when a post is selected on mobile
    window.addEventListener('post-selected', closeSidebar);
}

// ---------- SIDEBAR TREE ----------
let blogIndex = null;

async function loadBlogIndex() {
    try {
        const res = await fetch('content/index.json');
        blogIndex = await res.json();
        renderTree(blogIndex.tree);
        initSearch();

        // Check URL hash for direct linking
        if (window.location.hash) {
            const path = decodeURIComponent(window.location.hash.slice(1));
            loadPost(path);
        }

        // Listen for hash changes (back/forward)
        window.addEventListener('hashchange', () => {
            const path = decodeURIComponent(window.location.hash.slice(1));
            if (path) loadPost(path);
        });
    } catch (err) {
        console.error('Failed to load blog index:', err);
        document.getElementById('sidebar-tree').innerHTML =
            '<p style="padding:1.25rem;color:var(--text-dim);font-size:0.85rem;">No posts found yet.</p>';
    }
}

function renderTree(nodes, container, depth) {
    const parent = container || document.getElementById('sidebar-tree');
    const d = depth || 0;
    parent.innerHTML = '';

    nodes.forEach(node => {
        if (node.type === 'folder') {
            const folder = createFolderNode(node, d);
            parent.appendChild(folder);
        } else if (node.type === 'file') {
            const file = createFileNode(node);
            parent.appendChild(file);
        }
    });
}

function createFolderNode(node, depth) {
    const d = depth || 0;
    const li = document.createElement('div');
    li.className = 'tree-folder open'; // open by default
    li.setAttribute('data-depth', d);

    const label = document.createElement('button');
    label.className = 'tree-folder-label';
    label.setAttribute('data-folder-name', node.name.toLowerCase());
    label.innerHTML = `
        <span class="tree-folder-icon">▶</span>
        <span class="tree-folder-name-icon">${d === 0 ? '📂' : '📁'}</span>
        <span class="tree-folder-name">${node.name}</span>
    `;
    label.addEventListener('click', () => {
        li.classList.toggle('open');
    });

    const children = document.createElement('div');
    children.className = 'tree-folder-children';

    if (node.children) {
        node.children.forEach(child => {
            if (child.type === 'folder') {
                children.appendChild(createFolderNode(child, d + 1));
            } else if (child.type === 'file') {
                children.appendChild(createFileNode(child));
            }
        });
    }

    li.appendChild(label);
    li.appendChild(children);
    return li;
}

function createFileNode(node) {
    const btn = document.createElement('button');
    btn.className = 'tree-file-link';
    btn.setAttribute('data-path', node.path);
    btn.setAttribute('data-name', node.name.toLowerCase());
    btn.setAttribute('data-tags', (node.tags || []).join(' ').toLowerCase());

    const dateStr = node.date ? formatDate(node.date) : '';

    btn.innerHTML = `
        <span class="tree-file-icon">📄</span>
        <span class="tree-file-name">${node.name}</span>
        ${dateStr ? `<span class="tree-file-date">${dateStr}</span>` : ''}
    `;

    btn.addEventListener('click', () => {
        window.location.hash = encodeURIComponent(node.path);
    });

    return btn;
}

function formatDate(dateStr) {
    const d = new Date(dateStr);
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    return `${months[d.getMonth()]} ${d.getDate()}`;
}

// ---------- SEARCH ----------
function initSearch() {
    const input = document.getElementById('search-input');
    input.addEventListener('input', () => {
        const query = input.value.trim().toLowerCase();
        filterTree(query);
    });
}

function filterTree(query) {
    const files = document.querySelectorAll('.tree-file-link');
    const folders = document.querySelectorAll('.tree-folder');

    if (!query) {
        files.forEach(f => f.classList.remove('tree-hidden'));
        folders.forEach(f => {
            f.classList.remove('tree-hidden');
            f.classList.add('open');
        });
        return;
    }

    // First hide all files that don't match
    files.forEach(f => {
        const name = f.getAttribute('data-name') || '';
        const tags = f.getAttribute('data-tags') || '';
        const matches = name.includes(query) || tags.includes(query);
        f.classList.toggle('tree-hidden', !matches);
    });

    // Then show folders that have at least one visible child
    folders.forEach(folder => {
        const visibleChildren = folder.querySelectorAll('.tree-file-link:not(.tree-hidden)');
        folder.classList.toggle('tree-hidden', visibleChildren.length === 0);
        if (visibleChildren.length > 0) {
            folder.classList.add('open');
        }
    });
}

// ---------- POST LOADING ----------
async function loadPost(path) {
    try {
        const res = await fetch('content/' + path);
        if (!res.ok) throw new Error('Post not found');
        const md = await res.text();

        // Parse front-matter
        const { meta, body } = parseFrontMatter(md);

        // Show article, hide welcome
        document.getElementById('blog-welcome').style.display = 'none';
        const article = document.getElementById('blog-article');
        article.style.display = 'block';

        // Render breadcrumb
        renderBreadcrumb(path, meta.title);

        // Render meta
        renderMeta(meta, body);

        // Render body
        renderBody(body);

        // Highlight active link
        highlightActive(path);

        // Dispatch event for mobile sidebar close
        window.dispatchEvent(new Event('post-selected'));

        // Scroll to top
        window.scrollTo({ top: 0, behavior: 'smooth' });

    } catch (err) {
        console.error('Failed to load post:', err);
        document.getElementById('blog-article').style.display = 'block';
        document.getElementById('blog-welcome').style.display = 'none';
        document.getElementById('article-breadcrumb').innerHTML = '';
        document.getElementById('article-meta').innerHTML = '';
        document.getElementById('article-body').innerHTML = `
            <div class="blog-welcome" style="min-height:40vh;">
                <div class="welcome-icon">🔍</div>
                <h1>Post not found</h1>
                <p>The post you're looking for doesn't exist. Try selecting one from the sidebar.</p>
            </div>
        `;
    }
}

function parseFrontMatter(md) {
    const fmRegex = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/;
    const match = md.match(fmRegex);

    if (!match) {
        return { meta: {}, body: md };
    }

    const rawMeta = match[1];
    const body = match[2];
    const meta = {};

    rawMeta.split('\n').forEach(line => {
        const idx = line.indexOf(':');
        if (idx === -1) return;
        const key = line.slice(0, idx).trim();
        let value = line.slice(idx + 1).trim();

        // Parse arrays like [tag1, tag2]
        if (value.startsWith('[') && value.endsWith(']')) {
            value = value.slice(1, -1).split(',').map(s => s.trim().replace(/['"]/g, ''));
        }

        meta[key] = value;
    });

    return { meta, body };
}

function renderBreadcrumb(path, title) {
    const parts = path.split('/');
    const breadcrumb = document.getElementById('article-breadcrumb');

    let html = '<a href="./" class="breadcrumb-link">Blog</a>';

    // Show folder path as breadcrumbs (except the filename)
    for (let i = 0; i < parts.length - 1; i++) {
        const folderName = parts[i].replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
        html += `<span class="breadcrumb-separator">/</span>`;
        html += `<span class="breadcrumb-link">${folderName}</span>`;
    }

    // Current post
    const displayTitle = title || parts[parts.length - 1].replace('.md', '').replace(/-/g, ' ');
    html += `<span class="breadcrumb-separator">/</span>`;
    html += `<span class="breadcrumb-current">${displayTitle}</span>`;

    breadcrumb.innerHTML = html;
}

function renderMeta(meta, body) {
    const container = document.getElementById('article-meta');
    const wordCount = body.trim().split(/\s+/).length;
    const readingTime = Math.max(1, Math.ceil(wordCount / 200));

    let html = '';

    if (meta.title) {
        html += `<h1>${meta.title}</h1>`;
    }

    html += '<div class="article-meta-info">';
    if (meta.date) {
        const d = new Date(meta.date);
        const formatted = d.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });
        html += `<span class="meta-date">${formatted}</span>`;
    }
    html += `<span class="meta-reading">${readingTime} min read</span>`;
    html += '</div>';

    if (meta.tags && Array.isArray(meta.tags)) {
        html += '<div class="article-tags">';
        meta.tags.forEach(tag => {
            html += `<span class="article-tag">${tag}</span>`;
        });
        html += '</div>';
    }

    if (meta.description) {
        html += `<p class="article-description">${meta.description}</p>`;
    }

    container.innerHTML = html;
}

function renderBody(mdContent) {
    const container = document.getElementById('article-body');

    // Configure marked
    marked.setOptions({
        breaks: true,
        gfm: true,
        highlight: function(code, lang) {
            if (lang && hljs.getLanguage(lang)) {
                return hljs.highlight(code, { language: lang }).value;
            }
            return hljs.highlightAuto(code).value;
        }
    });

    container.innerHTML = marked.parse(mdContent);

    // Apply highlight.js to any blocks that weren't caught
    container.querySelectorAll('pre code').forEach(block => {
        hljs.highlightElement(block);
    });

    // Intercept internal .md links → route through hash navigation
    container.querySelectorAll('a').forEach(link => {
        const href = link.getAttribute('href') || '';
        if (href.endsWith('.md') && !href.startsWith('http')) {
            link.addEventListener('click', (e) => {
                e.preventDefault();
                // Strip leading "content/" if present (author convenience)
                const path = href.replace(/^content\//, '');
                window.location.hash = encodeURIComponent(path);
            });
        }
    });
}

function highlightActive(path) {
    document.querySelectorAll('.tree-file-link').forEach(link => {
        link.classList.toggle('active', link.getAttribute('data-path') === path);
    });
}

// ---------- SIDEBAR INIT ----------
function initSidebar() {
    // Sidebar is rendered after loadBlogIndex
}
