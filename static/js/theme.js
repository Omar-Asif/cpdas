// Theme toggle: switches data-theme on <html> and remembers the choice.
//
// The initial theme is set by an inline script in base.html's <head>, before
// this file loads, so the page never flashes the wrong theme. This file only
// has to handle the toggle button click after the page is interactive.

function setTheme(themeName) {
  document.documentElement.setAttribute("data-theme", themeName);
  localStorage.setItem("cpdas-theme", themeName);
}

function currentTheme() {
  return document.documentElement.getAttribute("data-theme");
}

document.addEventListener("DOMContentLoaded", function () {
  var toggleButton = document.getElementById("theme-toggle");
  if (!toggleButton) {
    return;
  }
  toggleButton.addEventListener("click", function () {
    var nextTheme = currentTheme() === "dark" ? "light" : "dark";
    setTheme(nextTheme);
  });
});
