// SPDX-License-Identifier: Apache-2.0

document.addEventListener("DOMContentLoaded", () => {
  const canonical = document.querySelector('link[rel="canonical"]');
  if (!canonical) return;

  const page = new URL(canonical.href).pathname.split("/").pop() || "index.html";
  const isRussian = page.endsWith(".ru.html");
  const english = page.replace(/\.ru\.html$/, ".html");
  const russian = english.replace(/\.html$/, ".ru.html");

  for (const link of document.querySelectorAll(".md-select a[hreflang], link[hreflang]")) {
    link.setAttribute("href", link.hreflang === "ru" ? russian : english);
  }

  if (!isRussian) return;
  document.documentElement.lang = "ru";

  const translations = {
    Overview: "Обзор",
    Usage: "Использование",
    Deployment: "Развёртывание",
    "External MX": "Внешний MX",
    Operations: "Эксплуатация",
    Developers: "Разработчикам",
  };

  const navigation = document.querySelectorAll(
    ".md-nav--primary .md-nav__link, .md-nav--primary .md-nav__title, " +
      ".md-tabs__link, a.md-logo",
  );
  for (const item of navigation) {
    const href = item.getAttribute("href");
    if (href?.endsWith(".html") && !href.endsWith(".ru.html")) {
      item.setAttribute("href", href.replace(/\.html$/, ".ru.html"));
    }
    const walker = document.createTreeWalker(item, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const label = node.textContent.trim();
      if (Object.hasOwn(translations, label)) {
        node.textContent = node.textContent.replace(label, translations[label]);
      }
    }
  }

  const current = window.location.pathname;
  const active = Array.from(document.querySelectorAll(".md-nav--primary a.md-nav__link"))
    .find((link) => link.pathname === current);
  if (!active) return;

  active.classList.add("md-nav__link--active");
  active.setAttribute("aria-current", "page");
  active.closest(".md-nav__item").classList.add("md-nav__item--active");

  // Zensical renders navigation from the English page list.
  const section = active.closest(".md-nav__item--nested");
  if (section) {
    section.classList.add("md-nav__item--active", "md-nav__item--section");
    const toggle = section.querySelector(".md-nav__toggle");
    toggle.classList.remove("md-toggle--indeterminate");
    toggle.checked = true;
    section.querySelector("nav").setAttribute("aria-expanded", "true");
  }

  const currentDirectory = current.slice(0, current.lastIndexOf("/") + 1);
  for (const tab of document.querySelectorAll(".md-tabs__link")) {
    if (tab.pathname.startsWith(currentDirectory) &&
        !tab.pathname.slice(currentDirectory.length).includes("/")) {
      tab.closest(".md-tabs__item").classList.add("md-tabs__item--active");
    }
  }
});
