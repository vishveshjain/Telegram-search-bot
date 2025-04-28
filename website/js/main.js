// Global state variables
let currentQuery = '';
let currentSource = '';
const pageSize = 10;

// Wait for the DOM to be fully loaded
document.addEventListener('DOMContentLoaded', function() {
    // Theme toggler functionality
    const themeToggle = document.querySelector('.theme-toggle');
    const body = document.body;
    
    // Check if user has a saved theme preference
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme === 'dark') {
        body.classList.add('dark-mode');
        themeToggle.querySelector('i').classList.replace('fa-moon', 'fa-sun');
    }
    
    // Toggle between light and dark themes
    themeToggle.addEventListener('click', function() {
        body.classList.toggle('dark-mode');
        
        // Update icon
        const icon = themeToggle.querySelector('i');
        if (body.classList.contains('dark-mode')) {
            icon.classList.replace('fa-moon', 'fa-sun');
            localStorage.setItem('theme', 'dark');
        } else {
            icon.classList.replace('fa-sun', 'fa-moon');
            localStorage.setItem('theme', 'light');
        }
    });
    
    // Search form functionality
    const searchForm = document.getElementById('search-form');
    const searchInput = document.getElementById('search-input');
    
    if (searchForm) {
        searchForm.addEventListener('submit', function(e) {
            e.preventDefault();
            const query = searchInput.value.trim();
            if (query) {
                currentQuery = query;
                currentSource = '';
                loadSearchResults(1);
            }
        });
    }
    
    // Smooth scrolling for anchor links
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function(e) {
            e.preventDefault();
            
            const targetId = this.getAttribute('href');
            if (targetId === '#') return;
            
            const targetElement = document.querySelector(targetId);
            if (targetElement) {
                window.scrollTo({
                    top: targetElement.offsetTop - 80, // Offset for header
                    behavior: 'smooth'
                });
            }
        });
    });
    
    // Add active class to nav links based on scroll position
    const sections = document.querySelectorAll('section[id]');
    const navLinks = document.querySelectorAll('.nav-links a');
    
    function highlightNavLink() {
        const scrollPosition = window.scrollY + 100;
        
        sections.forEach(section => {
            const sectionTop = section.offsetTop;
            const sectionHeight = section.offsetHeight;
            const sectionId = section.getAttribute('id');
            
            if (scrollPosition >= sectionTop && scrollPosition < sectionTop + sectionHeight) {
                navLinks.forEach(link => {
                    link.classList.remove('active');
                    if (link.getAttribute('href') === `#${sectionId}`) {
                        link.classList.add('active');
                    }
                });
            }
        });
    }
    
    window.addEventListener('scroll', highlightNavLink);
    
    // Initialize AOS (Animate On Scroll) if available
    if (typeof AOS !== 'undefined') {
        AOS.init({
            duration: 800,
            easing: 'ease-in-out',
            once: true
        });
    }
    
    // Simple animation for feature cards
    const featureCards = document.querySelectorAll('.feature-card');
    if (featureCards.length > 0) {
        featureCards.forEach((card, index) => {
            setTimeout(() => {
                card.style.opacity = '0';
                card.style.transform = 'translateY(20px)';
                setTimeout(() => {
                    card.style.transition = 'opacity 0.5s ease, transform 0.5s ease';
                    card.style.opacity = '1';
                    card.style.transform = 'translateY(0)';
                }, 100);
            }, index * 100);
        });
    }
    
    // Mobile navigation toggle (for smaller screens)
    // This would be implemented if we had a hamburger menu in the mobile view
    
    // Load trending sources dynamically
    function loadTrending(limit = 6) {
        fetch(`/api/sources?limit=${limit}`)
            .then(res => res.json())
            .then(sources => {
                const container = document.getElementById('trending-tags');
                container.innerHTML = sources.map(item => 
                    `<a href="#" class="tag" data-source="${item.source_name}">${item.source_name} <span>${item.count}</span></a>`
                ).join('');
                // Attach click handlers
                container.querySelectorAll('a.tag').forEach(tag => {
                    tag.addEventListener('click', e => {
                        e.preventDefault();
                        const sourceName = tag.dataset.source;
                        currentSource = sourceName;
                        currentQuery = '';
                        loadSourceResults(sourceName, 1);
                    });
                });
            })
            .catch(err => console.error(err));
    }
    
    // Load recent updates dynamically
    function loadRecent(limit = 6) {
        fetch(`/api/recent?limit=${limit}`)
            .then(res => res.json())
            .then(data => {
                const container = document.getElementById('recent-results');
                container.innerHTML = data.results.map(item => `
                    <div class="result-card" data-id="${item._id}">
                        <div class="result-date">${new Date(item.date).toLocaleDateString()}</div>
                        <h4>${item.file_name}</h4>
                        <p>${item.text.length > 100 ? item.text.slice(0, 100) + '...' : item.text}</p>
                        <div class="result-tags">
                            <span class="category">${item.file_type}</span>
                            <span class="source">${item.source_name}</span>
                        </div>
                    </div>
                `).join('');
                container.querySelectorAll('.result-card').forEach(card => {
                    card.addEventListener('click', () => openDocument(card.dataset.id));
                });
            })
            .catch(console.error);
    }
    
    // Initialize trending topics
    loadTrending();
    // Initialize recent updates
    loadRecent();
});

// Utility functions
function loadSearchResults(page) {
    // hide trending results
    document.getElementById('trending-results').style.display = 'none';
    document.getElementById('trending-pagination').style.display = 'none';
    // show search results
    document.getElementById('search-results').style.display = 'block';
    document.getElementById('pagination').style.display = 'block';
    fetch(`/api/search?q=${encodeURIComponent(currentQuery)}&page=${page}&page_size=${pageSize}`)
        .then(res => res.json())
        .then(data => {
            renderResults(data.results);
            renderPagination(data.total_pages, data.page, loadSearchResults);
            // scroll to search results section
            document.getElementById('results').scrollIntoView({ behavior: 'smooth' });
        })
        .catch(err => console.error(err));
}

function loadSourceResults(sourceName, page) {
    // hide search results
    document.getElementById('search-results').style.display = 'none';
    document.getElementById('pagination').style.display = 'none';
    // show trending results
    document.getElementById('trending-results').style.display = 'block';
    document.getElementById('trending-pagination').style.display = 'block';
    fetch(`/api/source/${encodeURIComponent(sourceName)}?page=${page}&page_size=${pageSize}`)
        .then(res => res.json())
        .then(data => {
            renderTrendingResults(data.results);
            renderTrendingPagination(data.total_pages, data.page, p => loadSourceResults(sourceName, p));
            // scroll to trending section
            document.getElementById('trending-tags').scrollIntoView({ behavior: 'smooth' });
        })
        .catch(err => console.error(err));
}

function renderResults(results) {
    const resultsContainer = document.getElementById('search-results');
    const countElem = document.getElementById('search-count');
    countElem.textContent = `${results.length} results`;
    resultsContainer.innerHTML = results.map(item => `
        <div class="result-card" data-id="${item._id}">
            <div class="result-date">${new Date(item.date).toLocaleDateString()}</div>
            <h4>${item.file_name}</h4>
            <p>${item.text.length>100 ? item.text.slice(0,100)+'...' : item.text}</p>
            <div class="result-tags">
                <span class="category">${item.file_type}</span>
                <span class="source">${item.source_name}</span>
            </div>
        </div>
    `).join('');
    resultsContainer.querySelectorAll('.result-card').forEach(card => {
        card.addEventListener('click', () => {
            openDocument(card.dataset.id);
        });
    });
}

function renderPagination(totalPages, currentPage, onPageClick) {
    const container = document.getElementById('pagination');
    let html = '';
    // Prev button
    if (currentPage > 1) {
        html += `<span class="page-prev" data-page="${currentPage-1}">Prev</span>`;
    }
    // Build page list with first, last, and neighbors
    let pages = [1];
    for (let i = currentPage-2; i <= currentPage+2; i++) {
        if (i > 1 && i < totalPages) pages.push(i);
    }
    if (totalPages > 1) pages.push(totalPages);
    pages = [...new Set(pages)].sort((a,b) => a-b);
    // Render with ellipsis
    let last = 0;
    pages.forEach(p => {
        if (last && p - last > 1) html += `<span class="ellipsis">...</span>`;
        html += `<span class="page-number${p===currentPage?' active':''}" data-page="${p}">${p}</span>`;
        last = p;
    });
    // Next button
    if (currentPage < totalPages) {
        html += `<span class="page-next" data-page="${currentPage+1}">Next</span>`;
    }
    container.innerHTML = html;
    container.querySelectorAll('.page-number, .page-prev, .page-next').forEach(el => {
        el.addEventListener('click', () => onPageClick(parseInt(el.dataset.page)));
    });
}

function renderTrendingResults(results) {
    const resultsContainer = document.getElementById('trending-results');
    resultsContainer.innerHTML = results.map(item => `
        <div class="result-card" data-id="${item._id}">
            <div class="result-date">${new Date(item.date).toLocaleDateString()}</div>
            <h4>${item.file_name}</h4>
            <p>${item.text.length>100 ? item.text.slice(0,100)+'...' : item.text}</p>
            <div class="result-tags">
                <span class="category">${item.file_type}</span>
                <span class="source">${item.source_name}</span>
            </div>
        </div>
    `).join('');
    resultsContainer.querySelectorAll('.result-card').forEach(card => {
        card.addEventListener('click', () => openDocument(card.dataset.id));
    });
}

function renderTrendingPagination(totalPages, currentPage, onPageClick) {
    const container = document.getElementById('trending-pagination');
    let html = '';
    if (currentPage > 1) {
        html += `<span class="page-prev" data-page="${currentPage-1}">Prev</span>`;
    }
    let pages = [1];
    for (let i = currentPage-2; i <= currentPage+2; i++) {
        if (i > 1 && i < totalPages) pages.push(i);
    }
    if (totalPages > 1) pages.push(totalPages);
    pages = [...new Set(pages)].sort((a,b) => a-b);
    let last = 0;
    pages.forEach(p => {
        if (last && p - last > 1) html += `<span class="ellipsis">...</span>`;
        html += `<span class="page-number${p===currentPage?' active':''}" data-page="${p}">${p}</span>`;
        last = p;
    });
    if (currentPage < totalPages) {
        html += `<span class="page-next" data-page="${currentPage+1}">Next</span>`;
    }
    container.innerHTML = html;
    container.querySelectorAll('.page-number, .page-prev, .page-next').forEach(el => {
        el.addEventListener('click', () => onPageClick(parseInt(el.dataset.page)));
    });
}

function openDocument(docId) {
    fetch(`/api/document/${docId}`)
        .then(res => res.json())
        .then(doc => {
            const modal = document.getElementById('document-modal');
            modal.style.display = 'block';
            const modalBody = document.getElementById('modal-body');
            const hasMedia = doc.mime_type && (
                doc.mime_type.startsWith('video/') ||
                doc.mime_type.startsWith('image/') ||
                doc.mime_type.startsWith('audio/') ||
                doc.mime_type === 'application/pdf'
            );
            if (hasMedia) {
                modalBody.innerHTML = '<div class="buffer-container"><div class="buffer-bar"></div></div><div class="buffer-text">Loading: 0%</div>';
            } else {
                modalBody.innerHTML = '';
            }
            document.getElementById('modal-title').textContent = doc.file_name;
            document.getElementById('modal-date').textContent = new Date(doc.date).toLocaleString();
            // Render media if available
            let content = '';
            if (doc.media_url) {
                if (doc.mime_type.startsWith('video/')) {
                    content += `<video controls preload="auto" style="width:100%; max-height:400px; margin-bottom:1em;"></video>`;
                } else if (doc.mime_type.startsWith('image/')) {
                    content += `<img src="${doc.media_url}" style="width:100%; margin-bottom:1em;" onload="this.previousSibling.remove()" />`;
                } else if (doc.mime_type.startsWith('audio/')) {
                    content += `<audio controls src="${doc.media_url}" style="width:100%; margin-bottom:1em;" onloadedmetadata="this.previousSibling.remove()"></audio>`;
                } else if (doc.mime_type === 'application/pdf') {
                    content += `<iframe src="${doc.media_url}#view=fitH" type="application/pdf" width="100%" height="600px" style="margin-bottom:1em; border:none;"></iframe>`;
                }
            } else {
                content += `<p>No media available.</p>`;
            }
            // Process text and embed URLs
            const urlRegex = /(https?:\/\/[^\s]+)/g;
            doc.text.split(urlRegex).forEach(part => {
                if (urlRegex.test(part)) {
                    try {
                        const url = new URL(part);
                        // X.com/Twitter: display as hyperlink only
                        if (url.hostname.includes('x.com') || url.hostname.includes('twitter.com')) {
                            content += `<a href="${part}" target="_blank" style="display:block; margin-bottom:1em;">${part}</a>`;
                            return;
                        }
                        // YouTube embed: support youtu.be, /watch, /shorts, /live
                        let vid = null;
                        if (url.hostname.includes('youtu.be')) {
                            vid = url.pathname.slice(1);
                        } else if (url.hostname.includes('youtube.com') || url.hostname.includes('www.youtube.com')) {
                            const p = url.pathname;
                            if (p.startsWith('/watch')) {
                                vid = url.searchParams.get('v');
                            } else if (p.startsWith('/shorts/')) {
                                vid = p.split('/')[2];
                            } else if (p.startsWith('/live/')) {
                                vid = p.split('/')[2];
                            }
                        }
                        if (vid) {
                            content += `<iframe width="100%" height="360" src="https://www.youtube.com/embed/${vid}" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen style="margin-bottom:1em;"></iframe>`;
                            return;
                        }
                        // Rumble embed blocked; fallback to hyperlink
                        else if (url.hostname.includes('rumble.com')) {
                            content += `<a href="${part}" target="_blank" style="display:block; margin-bottom:1em;">${part}</a>`;
                            return;
                        }
                        // Generic embed for other URLs with fallback link
                        content += `<object data="${part}" width="100%" height="400" style="margin-bottom:1em;"><a href="${part}" target="_blank">${part}</a></object>`;
                    } catch (e) {
                        content += `<a href="${part}" target="_blank">${part}</a>`;
                    }
                } else {
                    content += `<p>${part}</p>`;
                }
            });
            modalBody.insertAdjacentHTML('beforeend', content);
            // Fallback hyperlink for iframes that refuse to load
            modalBody.querySelectorAll('iframe').forEach(iframe => {
                iframe.addEventListener('error', () => {
                    const href = iframe.src;
                    const link = document.createElement('a');
                    link.href = href;
                    link.textContent = href;
                    link.target = '_blank';
                    link.style.display = 'block';
                    iframe.replaceWith(link);
                });
            });
            // Skip buffering setup when not a media file
            if (!hasMedia) return;
            // Setup video buffering progress using XHR
            const bufferContainer = modalBody.querySelector('.buffer-container');
            const bufferBar = bufferContainer.querySelector('.buffer-bar');
            const bufferText = modalBody.querySelector('.buffer-text');
            const videoEl = modalBody.querySelector('video');
            if (videoEl) {
                // Use XHR to fetch media with progress events
                const url = doc.media_url;
                const xhr = new XMLHttpRequest();
                xhr.open('GET', url, true);
                xhr.responseType = 'blob';
                xhr.onprogress = event => {
                    if (event.lengthComputable) {
                        const percent = Math.floor(event.loaded / event.total * 100);
                        bufferBar.style.width = percent + '%';
                        bufferText.textContent = 'Loading: ' + percent + '%';
                    }
                };
                xhr.onload = () => {
                    bufferContainer.remove();
                    bufferText.remove();
                    videoEl.src = URL.createObjectURL(xhr.response);
                };
                xhr.onerror = () => {
                    bufferContainer.remove();
                    bufferText.remove();
                    videoEl.src = url;
                };
                xhr.send();
            }
            // Fallback removal for images and audio
            const fallbackMedia = modalBody.querySelector('img, audio');
            if (fallbackMedia) {
                const eventName = fallbackMedia.tagName === 'IMG' ? 'load' : 'canplaythrough';
                fallbackMedia.addEventListener(eventName, () => {
                    bufferContainer.remove();
                    bufferText.remove();
                });
            }
            // Remove loader for PDF iframe
            const pdfIframe = modalBody.querySelector('iframe[type="application/pdf"]');
            if (pdfIframe) {
                pdfIframe.addEventListener('load', () => {
                    bufferContainer.remove(); bufferText.remove();
                });
            }
            // Initialize Twitter widgets if available
            if (window.twttr && twttr.widgets && typeof twttr.widgets.load === 'function') {
                twttr.widgets.load(document.getElementById('modal-body'));
            }
        });
}

// Modal close handler
const modal = document.getElementById('document-modal');
modal.querySelector('.close').addEventListener('click', () => {
    document.getElementById('modal-body').innerHTML = '';
    modal.style.display = 'none';
});

// Removed getRumbleEmbedCode: Rumble embedding is not supported due to X-Frame/CORS restrictions
