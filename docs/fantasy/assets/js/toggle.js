function setChange(type, btn) {
  // active button styling
  document.querySelectorAll(".type-toggle button").forEach(b => b.classList.remove("active"));
  if (btn) btn.classList.add("active");
}

// default = whatever button has class active (yours is 2 Weeks)
document.addEventListener("DOMContentLoaded", () => {
  const defaultBtn = document.querySelector(".type-toggle button.active");
  if (defaultBtn) defaultBtn.click();
});