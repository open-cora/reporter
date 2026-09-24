/* Fades the hero's wash and type out as the plate scrolls away, so the page
   header underneath takes over cleanly. The wash defaults to fully opaque in
   CSS, so the hero is correct with this script absent or blocked. */
(function () {
  var hero = document.querySelector(".hero");
  if (!hero) return;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

  var ticking = false;

  function apply() {
    var travel = hero.offsetHeight || 1;
    var fade = 1 - Math.min(window.scrollY / travel, 1);
    hero.style.setProperty("--hero-fade", fade.toFixed(3));
    ticking = false;
  }

  function onScroll() {
    if (ticking) return;
    ticking = true;
    window.requestAnimationFrame(apply);
  }

  apply();
  window.addEventListener("scroll", onScroll, { passive: true });
  window.addEventListener("resize", onScroll, { passive: true });
})();
