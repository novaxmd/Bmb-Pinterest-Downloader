import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Bmb Pinterest Downloader (HD) – Download Pinterest Videos Free",
  description: "Download Pinterest videos in HD for free. Fast, secure and no login required. Convert Pinterest videos to MP4 instantly.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <head>
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{
            __html: JSON.stringify({
              "@context": "https://schema.org",
              "@type": "FAQPage",
              mainEntity: [
                {
                  "@type": "Question",
                  name: "Can I download Pinterest videos in MP4 format?",
                  acceptedAnswer: {
                    "@type": "Answer",
                    text: "Yes, our tool automatically converts Pinterest videos into MP4 format for easy downloading.",
                  },
                },
                {
                  "@type": "Question",
                  name: "Is this Pinterest downloader free?",
                  acceptedAnswer: {
                    "@type": "Answer",
                    text: "Yes, it is completely free with no hidden charges.",
                  },
                },
                {
                  "@type": "Question",
                  name: "Why do some videos take longer to download?",
                  acceptedAnswer: {
                    "@type": "Answer",
                    text: "Some Pinterest videos use streaming format (HLS). These videos are converted into MP4 before downloading.",
                  },
                },
                {
                  "@type": "Question",
                  name: "Can I use this tool on mobile?",
                  acceptedAnswer: {
                    "@type": "Answer",
                    text: "Yes, our downloader works perfectly on mobile devices.",
                  },
                },
              ],
            }),
          }}
        />
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{
            __html: JSON.stringify({
              "@context": "https://schema.org",
              "@type": "WebApplication",
              name: "Bmb Pinterest Downloader",
              url: "https://pintrestvideodownloader.com",
              applicationCategory: "Multimedia",
              operatingSystem: "All",
              description:
                "Download Pinterest videos in HD quality instantly. Convert Pinterest videos to MP4 online for free.",
              browserRequirements: "Requires JavaScript",
            }),
          }}
        />
      </head>
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        {children}
      </body>
    </html>
  );
}
