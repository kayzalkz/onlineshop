document.addEventListener("DOMContentLoaded", function() {
    const sidebar = document.querySelector('.sidebar');
    const toggleBtn = document.getElementById('sidebarToggle');
    const body = document.body;

    // 1. Overlay for Mobile
    const overlay = document.createElement('div');
    overlay.className = 'sidebar-overlay';
    overlay.style.cssText = "position:fixed;top:0;left:0;width:100vw;height:100vh;background:rgba(0,0,0,0.4);z-index:900;display:none;";
    body.appendChild(overlay);

    function toggleSidebar() {
        sidebar.classList.toggle('active');
        overlay.style.display = sidebar.classList.contains('active') ? 'block' : 'none';
    }

    if (toggleBtn) {
        toggleBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            toggleSidebar();
        });
    }

    overlay.addEventListener('click', toggleSidebar);

    // 2. Swipe Gestures
    let touchStartX = 0;
    document.addEventListener('touchstart', e => { touchStartX = e.changedTouches[0].screenX; }, {passive: true});
    document.addEventListener('touchend', e => {
        let touchEndX = e.changedTouches[0].screenX;
        let diff = touchEndX - touchStartX;
        if (diff > 100 && touchStartX < 50) toggleSidebar(); // Swipe Right to open
        if (diff < -100 && sidebar.classList.contains('active')) toggleSidebar(); // Swipe Left to close
    }, {passive: true});

    // 3. Auto-dismiss alerts
    setTimeout(() => {
        document.querySelectorAll('.alert').forEach(a => {
            a.style.opacity = '0';
            setTimeout(() => a.remove(), 500);
        });
    }, 4000);
});
