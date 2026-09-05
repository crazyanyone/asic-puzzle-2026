document.querySelectorAll(".fold-toggle").forEach((button) => {
  button.addEventListener("click", () => {
    const fold = button.closest(".fold");
    const collapsed = fold.classList.toggle("is-collapsed");
    button.textContent = collapsed ? "▸" : "▾";
  });
});

function setAll(collapsed) {
  document.querySelectorAll(".fold").forEach((fold) => {
    fold.classList.toggle("is-collapsed", collapsed);
    const button = fold.querySelector(".fold-toggle");
    if (button) button.textContent = collapsed ? "▸" : "▾";
  });
}

document.getElementById("collapse-all")?.addEventListener("click", () => setAll(true));
document.getElementById("expand-all")?.addEventListener("click", () => setAll(false));
