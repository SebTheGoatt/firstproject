// ============================================
//  VetPath – Shared JavaScript
// ============================================

// Mobile nav toggle
document.addEventListener('DOMContentLoaded', () => {
  const hamburger = document.getElementById('hamburger');
  const navLinks  = document.getElementById('nav-links');

  if (hamburger && navLinks) {
    hamburger.addEventListener('click', () => {
      navLinks.classList.toggle('open');
    });

    // Close nav when a link is clicked
    navLinks.querySelectorAll('a').forEach(link => {
      link.addEventListener('click', () => {
        navLinks.classList.remove('open');
      });
    });
  }

  // Mark active nav link based on current page
  const currentPath = window.location.pathname;
  document.querySelectorAll('.navbar-links a').forEach(link => {
    link.classList.remove('active');
    const href = link.getAttribute('href');
    if (
      (currentPath === '/' && href === '/') ||
      (currentPath !== '/' && href !== '/' && currentPath.startsWith(href.replace('.html', '')))
    ) {
      if (!link.classList.contains('btn-nav')) {
        link.classList.add('active');
      }
    }
  });
});
