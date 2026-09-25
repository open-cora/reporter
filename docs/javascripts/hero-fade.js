/* Fades the hero's wash and type out as the plate scrolls away, so the page
   header underneath takes over cleanly. The wash defaults to fully opaque in
   CSS, so the hero is correct with this script absent or blocked.

   Also measures the header and Home tab so the plate can bleed up behind
   them (--topnav-height, read by hero.css), and flips .hero-scrolled on once
   the page passes the hero, which is what gives the header its background
   color back. Without that class the header's white text would sit on the
   plain white page below the hero and disappear. Both run even under
   reduced motion, since neither animates a position, only a class and a
   custom property; only the continuous fade is gated on that preference. */
(function () {
  var hero = document.querySelector(".hero");
  if (!hero) return;

  var header = document.querySelector(".md-header");
  var tabs = document.querySelector(".md-tabs");

  function measureTopnav() {
    var height = header ? header.offsetHeight : 0;
    if (tabs && getComputedStyle(tabs).display !== "none") {
      height += tabs.offsetHeight;
    }
    document.documentElement.style.setProperty("--topnav-height", height + "px");
  }

  function toggleScrolled() {
    var headerHeight = header ? header.offsetHeight : 0;
    var threshold = Math.max(hero.offsetHeight - headerHeight, 0);
    document.body.classList.toggle("hero-scrolled", window.scrollY > threshold);
  }

  measureTopnav();
  toggleScrolled();
  window.addEventListener("resize", measureTopnav);
  window.addEventListener("resize", toggleScrolled);

  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    window.addEventListener("scroll", toggleScrolled, { passive: true });
    return;
  }

  var ticking = false;

  function apply() {
    var travel = hero.offsetHeight || 1;
    var fade = 1 - Math.min(window.scrollY / travel, 1);
    hero.style.setProperty("--hero-fade", fade.toFixed(3));
    ticking = false;
  }

  function onScroll() {
    toggleScrolled();
    if (ticking) return;
    ticking = true;
    window.requestAnimationFrame(apply);
  }

  apply();
  window.addEventListener("scroll", onScroll, { passive: true });
  window.addEventListener("resize", onScroll, { passive: true });
})();
