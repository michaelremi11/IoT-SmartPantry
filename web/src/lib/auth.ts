"use client";

import {
  createUserWithEmailAndPassword,
  onAuthStateChanged,
  signInWithEmailAndPassword,
  signOut,
  updateProfile,
  User,
} from "firebase/auth";
import {
  collection,
  doc,
  getDoc,
  serverTimestamp,
  writeBatch,
} from "firebase/firestore";
import { auth, db } from "./firebase";

export type SessionUser = {
  uid: string;
  email: string;
  displayName: string;
  householdId: string;
  householdName: string;
};

type UserProfileDoc = {
  uid: string;
  email: string;
  displayName: string;
  householdId: string;
  householdName?: string;
};

function displayNameFromUser(user: User): string {
  const emailName = user.email?.split("@")[0]?.trim() || "Pantry User";
  return user.displayName?.trim() || emailName;
}

async function createDefaultHousehold(user: User, householdName?: string) {
  const resolvedName = householdName?.trim() || `${displayNameFromUser(user)} Household`;
  const householdRef = doc(collection(db, "households"));
  const userRef = doc(db, "users", user.uid);
  const batch = writeBatch(db);

  batch.set(householdRef, {
    name: resolvedName,
    ownerUid: user.uid,
    memberUids: [user.uid],
    createdAt: serverTimestamp(),
    updatedAt: serverTimestamp(),
  });
  batch.set(userRef, {
    uid: user.uid,
    email: user.email || "",
    displayName: displayNameFromUser(user),
    householdId: householdRef.id,
    householdName: resolvedName,
    createdAt: serverTimestamp(),
    updatedAt: serverTimestamp(),
  });

  await batch.commit();
}

async function ensureUserProfile(user: User): Promise<SessionUser> {
  const userRef = doc(db, "users", user.uid);
  const userSnap = await getDoc(userRef);

  if (!userSnap.exists()) {
    await createDefaultHousehold(user);
  }

  const profileSnap = await getDoc(userRef);
  const profile = profileSnap.data() as UserProfileDoc | undefined;
  if (!profile?.householdId) {
    throw new Error("This account is missing a household profile.");
  }

  return {
    uid: user.uid,
    email: user.email || profile.email || "",
    displayName: profile.displayName || displayNameFromUser(user),
    householdId: profile.householdId,
    householdName: profile.householdName || "My Pantry",
  };
}

export async function registerWithEmail(input: {
  email: string;
  password: string;
  displayName?: string;
  householdName?: string;
}) {
  const cred = await createUserWithEmailAndPassword(auth, input.email, input.password);
  if (input.displayName?.trim()) {
    await updateProfile(cred.user, { displayName: input.displayName.trim() });
  }
  const resolvedHouseholdName =
    input.householdName?.trim() ||
    (input.displayName?.trim() ? `${input.displayName.trim()} Pantry` : undefined);
  await createDefaultHousehold(cred.user, resolvedHouseholdName);
  return ensureUserProfile(cred.user);
}

export async function loginWithEmail(email: string, password: string) {
  const cred = await signInWithEmailAndPassword(auth, email, password);
  return ensureUserProfile(cred.user);
}

export async function logout() {
  await signOut(auth);
}

export function subscribeToSession(
  callback: (session: SessionUser | null, loading: boolean) => void
) {
  callback(null, true);
  return onAuthStateChanged(auth, async (user) => {
    if (!user) {
      callback(null, false);
      return;
    }
    try {
      const session = await ensureUserProfile(user);
      callback(session, false);
    } catch (error) {
      console.error("Failed to load user profile", error);
      callback(null, false);
    }
  });
}
