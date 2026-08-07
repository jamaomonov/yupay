import Image from "next/image";

/**
 * Hero product visual — one large, static screenshot of the YuPay Telegram
 * mini app (the catalog / home screen) on a soft lime bloom. No animation,
 * no overlay chips: the product shot carries the hero on its own.
 *
 * Server component — just an image + a static glow.
 */
export function PhoneShowcase() {
  return (
    <div className="relative mx-auto w-full max-w-[600px]">
      {/* Static lime bloom behind the device */}
      <div
        aria-hidden
        className="glow-lime absolute left-1/2 top-1/2"
        style={{
          width: 620,
          height: 620,
          transform: "translate(-50%, -50%)",
        }}
      />

      <Image
        src="/mockups/home.png"
        alt="Главный экран каталога приложения yupay"
        width={2000}
        height={1964}
        priority
        // Measured as the LCP element of the home page. `priority` does not set
        // the request priority on its own — see the note on the brand hero.
        fetchPriority="high"
        sizes="(max-width: 768px) 92vw, 580px"
        className="relative h-auto w-full drop-shadow-[0_45px_90px_rgba(0,0,0,0.6)]"
      />
    </div>
  );
}
