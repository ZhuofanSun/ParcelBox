const AVATAR_STORAGE_KEY = "parcelbox.profile_avatar";

export async function loadProfileAvatarDataUrl() {
  const stored = window.localStorage.getItem(AVATAR_STORAGE_KEY);
  return typeof stored === "string" && stored.trim() ? stored : null;
}

export async function saveProfileAvatarDataUrl(dataUrl) {
  if (typeof dataUrl !== "string" || !dataUrl.trim()) {
    throw new Error("Avatar data is empty");
  }

  try {
    window.localStorage.setItem(AVATAR_STORAGE_KEY, dataUrl);
  } catch (error) {
    throw new Error(
      error instanceof Error ? error.message : "Avatar storage quota exceeded"
    );
  }
}

export async function clearProfileAvatarDataUrl() {
  window.localStorage.removeItem(AVATAR_STORAGE_KEY);
}
