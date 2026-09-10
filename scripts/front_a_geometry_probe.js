(() => {
  function isVisible(element) {
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
  }

  function hasClippingAncestor(element) {
    let parent = element.parentElement;
    while (parent) {
      const style = getComputedStyle(parent);
      if (["auto", "scroll", "hidden", "clip"].includes(style.overflowX)) return true;
      parent = parent.parentElement;
    }
    return false;
  }

  function isFullyPaintable(element) {
    const rect = element.getBoundingClientRect();
    if (rect.left < 0 || rect.right > innerWidth || rect.top < 0 || rect.bottom > innerHeight) return false;
    let parent = element.parentElement;
    while (parent) {
      const style = getComputedStyle(parent);
      if (["auto", "scroll", "hidden", "clip"].includes(style.overflowX) ||
          ["auto", "scroll", "hidden", "clip"].includes(style.overflowY)) {
        const parentRect = parent.getBoundingClientRect();
        if (rect.left < parentRect.left || rect.right > parentRect.right ||
            rect.top < parentRect.top || rect.bottom > parentRect.bottom) return false;
      }
      parent = parent.parentElement;
    }
    return true;
  }

  function frontAGeometryProbe() {
    const failures = [...document.querySelectorAll("body *")]
      .filter(isVisible)
      .filter((element) => {
        const rect = element.getBoundingClientRect();
        return !hasClippingAncestor(element) && (rect.left < -1 || rect.right > innerWidth + 1);
      })
      .map((element) => {
        const rect = element.getBoundingClientRect();
        return {
          tag: element.tagName,
          className: String(element.className || ""),
          left: Math.round(rect.left),
          right: Math.round(rect.right),
        };
      });
    const actionBar = document.querySelector(
      "#email-preview-panel .email-modal-footer, .visual-document-review .visual-document-actions"
    );
    const actionRect = actionBar ? actionBar.getBoundingClientRect() : null;
    const actionControls = actionBar
      ? [...actionBar.querySelectorAll("button, a")].filter(isVisible)
      : [];
    return {
      viewport: { width: innerWidth, height: innerHeight },
      uncontainedDescendantOverflow: failures,
      actionBar: actionRect
        ? {
            left: Math.round(actionRect.left),
            right: Math.round(actionRect.right),
            top: Math.round(actionRect.top),
            bottom: Math.round(actionRect.bottom),
            fullyVisible:
              actionRect.left >= 0 &&
              actionRect.right <= innerWidth &&
              actionRect.top >= 0 &&
              actionRect.bottom <= innerHeight &&
              isFullyPaintable(actionBar) &&
              actionControls.length > 0 &&
              actionControls.every(isFullyPaintable),
            controls: actionControls.map((control) => {
              const rect = control.getBoundingClientRect();
              return {
                label: (control.textContent || "").trim(),
                top: Math.round(rect.top),
                bottom: Math.round(rect.bottom),
                fullyVisible: isFullyPaintable(control),
              };
            }),
          }
        : null,
    };
  }
  return frontAGeometryProbe();
})();
