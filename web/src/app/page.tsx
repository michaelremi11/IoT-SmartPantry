import HomeClient from "./home_client";

export const metadata = {
  title: "Smart Pantry Hub — Dashboard",
  description: "Remotely view your pantry inventory, shopping list and kitchen analytics.",
};

export default function HomePage() {
  return <HomeClient />;
}