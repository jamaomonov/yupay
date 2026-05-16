import { Button } from "@yupay/ui";

export default function HomePage() {
  return (
    <main className="flex min-h-screen flex-col items-start justify-center gap-6 p-6">
      <h1 className="text-3xl font-semibold">YuPay</h1>
      <p className="text-[--color-muted]">Telegram Mini App</p>
      <Button>Каталог</Button>
    </main>
  );
}
