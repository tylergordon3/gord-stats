document.addEventListener("DOMContentLoaded", () => {
  const menuBtn = document.querySelector(".nav-menu-btn");
  const drawer = document.getElementById("mobile-drawer");
  const overlay = document.querySelector(".nav-overlay");

  if (!menuBtn || !drawer || !overlay) return;

  menuBtn.addEventListener("click", () => {
    drawer.classList.add("open");
    overlay.classList.add("show");
  });

  overlay.addEventListener("click", () => {
    drawer.classList.remove("open");
    overlay.classList.remove("show");
  });

  // Optional: close drawer when a link is clicked
  drawer.querySelectorAll("a").forEach(link => {
    link.addEventListener("click", () => {
      drawer.classList.remove("open");
      overlay.classList.remove("show");
    });
  });
});
