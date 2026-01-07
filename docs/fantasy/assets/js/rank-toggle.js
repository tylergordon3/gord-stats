function normText(s) {
  return (s || "")
    .replace(/\u00A0/g, " ")     // NBSP -> space
    .replace(/\s+/g, " ")       // collapse whitespace
    .trim();
}

function setChangeT(type, btn) {

  document.querySelectorAll(".table-scroll").forEach(div => {
    div.classList.add("hidden-div");
  })

  const inj = document.querySelectorAll(".active.injury-toggle").getAttribute('data-key')

  // Get all tables with the class "table-scroll"
  const target = document.querySelector(`.table-scroll.${type}.${inj}`);
  if (target) target.classList.remove("hidden-div");

  // active button styling
  if (btn.classList.contains("type-toggle")) {
    document.querySelectorAll(" button.type-toggle").forEach(b => b.classList.remove("active"));
    if (btn) btn.classList.add("active");
  }
}

function setChangeI(inj, btn) {

  document.querySelectorAll(".table-scroll").forEach(div => {
    div.classList.add("hidden-div");
  })

  const type = document.querySelectorAll(".active.type-toggle").getAttribute('data-key')

  // Get all tables with the class "table-scroll"
  const target = document.querySelector(`.table-scroll.${type}.${inj}`);
  if (target) target.classList.remove("hidden-div");

  // active button styling
  if (btn.classList.contains("injury-toggle")) {
    document.querySelectorAll("button.injuy-toggle").forEach(b => b.classList.remove("active"));
    if (btn) btn.classList.add("active");
  }
}

// default = whatever button has class active (yours is 2 Weeks)
document.addEventListener("DOMContentLoaded", () => {
  const defaultTypeBtn = document.querySelector(".type-toggle button.active");
  if (defaultTypeBtn) defaultTypeBtn.click();
  const defaultInjBtn = document.querySelector(".injury-toggle button.active");
  if (defaultInjBtn) defaultInjBtn.click();
});