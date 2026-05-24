import arenaLogo from "@assets/arenabreakout_1778456340557.svg";
import arenaBg from "@assets/arenabreakout_bg_1778456340546.png";
import deltaforceAppIcon from "@assets/deltaforce_1778598588753.webp";
import pubgAppIcon from "@assets/pubgm_1778598588751.webp";
import pubgLogo from "@assets/pubgmobile_1778456340545.svg";
import pubgBg from "@assets/pubgmobile_bg_1778456340557.png";
import steamBg from "@assets/steam_bg_1778459971795.jpg";
import telegramBg from "@assets/telegram-bg_1778459971796.jpg";
import telegramAppIcon from "@assets/telegram_1778598588753.webp";
import {
  SiSteam,
  SiRiotgames,
  SiRoblox,
  SiEpicgames,
  SiTelegram,
  SiGoogleplay,
} from "react-icons/si";

export type Category = "games" | "services" | "cards";

export interface Game {
  id: string;
  name: string;
  publisher: string;
  category: Category;
  appIcon?: string;
  logoUrl?: string;
  bgUrl?: string;
  icon?: any;
  iconColor?: string;
  color: string;
  gradient?: string;
  inputType: string;
  inputPlaceholder: string;
  featured?: boolean;
  featuredDesc?: string;
}

export const CATEGORY_LABELS: Record<Category, string> = {
  games: "Игры",
  services: "Сервисы",
  cards: "Подарочные карты",
};

export const GAMES: Game[] = [
  {
    id: "pubg",
    name: "PUBG Mobile",
    publisher: "Tencent Games",
    category: "games",
    appIcon: pubgAppIcon,
    logoUrl: pubgLogo,
    bgUrl: pubgBg,
    color: "#ff9900",
    inputType: "Player ID",
    inputPlaceholder: "Введите ваш Player ID",
    featured: true,
    featuredDesc: "Покупай UC и прокачивай Royale Pass",
  },
  {
    id: "telegram",
    name: "Telegram Premium",
    publisher: "Telegram FZ-LLC",
    category: "services",
    appIcon: telegramAppIcon,
    icon: SiTelegram,
    iconColor: "#2aabee",
    bgUrl: telegramBg,
    color: "#2aabee",
    gradient: "from-[#2aabee] to-[#229ed9]",
    inputType: "Номер телефона",
    inputPlaceholder: "+7 (999) 000-00-00",
    featured: true,
    featuredDesc: "Активируй Telegram Premium на год",
  },
  {
    id: "delta-force",
    name: "Delta Force",
    publisher: "Team Jade",
    category: "games",
    appIcon: deltaforceAppIcon,
    color: "#c8a96e",
    gradient: "from-[#1a1a1a] to-[#2d2416]",
    inputType: "Player ID",
    inputPlaceholder: "Введите ваш Player ID",
  },
  {
    id: "steam",
    name: "Steam",
    publisher: "Valve",
    category: "services",
    icon: SiSteam,
    iconColor: "#c7d5e0",
    bgUrl: steamBg,
    color: "#c7d5e0",
    gradient: "from-[#171a21] to-[#1b2838]",
    inputType: "Логин",
    inputPlaceholder: "Введите логин Steam",
    featured: true,
    featuredDesc: "Пополни кошелёк Steam мгновенно",
  },
  {
    id: "arena-breakout",
    name: "Arena Breakout",
    publisher: "Level Infinite",
    category: "games",
    logoUrl: arenaLogo,
    bgUrl: arenaBg,
    color: "#ffffff",
    inputType: "Player ID",
    inputPlaceholder: "Введите ваш Player ID",
  },
  {
    id: "valorant",
    name: "Valorant",
    publisher: "Riot Games",
    category: "games",
    icon: SiRiotgames,
    iconColor: "#ff4655",
    color: "#ff4655",
    gradient: "from-[#ff4655] to-[#0f1923]",
    inputType: "Riot ID",
    inputPlaceholder: "Например: Player#EUNE",
  },
  {
    id: "roblox",
    name: "Roblox",
    publisher: "Roblox Corp",
    category: "games",
    icon: SiRoblox,
    iconColor: "#ffffff",
    color: "#ffffff",
    gradient: "from-[#111111] to-[#333333]",
    inputType: "Username",
    inputPlaceholder: "Введите никнейм",
  },
  {
    id: "epic",
    name: "Epic Games",
    publisher: "Epic Games",
    category: "services",
    icon: SiEpicgames,
    iconColor: "#ffffff",
    color: "#ffffff",
    gradient: "from-[#111111] to-[#333333]",
    inputType: "Email",
    inputPlaceholder: "Email от аккаунта",
  },
  {
    id: "steam-card",
    name: "Steam Gift Card",
    publisher: "Valve",
    category: "cards",
    icon: SiSteam,
    iconColor: "#c7d5e0",
    color: "#c7d5e0",
    gradient: "from-[#1b2838] to-[#2a475e]",
    inputType: "Email",
    inputPlaceholder: "Email для отправки карты",
  },
  {
    id: "google-play",
    name: "Google Play",
    publisher: "Google",
    category: "cards",
    icon: SiGoogleplay,
    color: "#4285f4",
    gradient: "from-[#4285f4] to-[#34a853]",
    inputType: "Email",
    inputPlaceholder: "Email аккаунта Google",
    iconColor: "#ffffff",
  },
];

export const FEATURED_GAMES = GAMES.filter((g) => g.featured);

export const HISTORY = [
  {
    id: "tx-1",
    gameId: "pubg",
    amount: 1000,
    date: "12 Мая 2024, 14:30",
    status: "success",
  },
  {
    id: "tx-2",
    gameId: "valorant",
    amount: 500,
    date: "10 Мая 2024, 09:15",
    status: "processing",
  },
  {
    id: "tx-3",
    gameId: "steam",
    amount: 2000,
    date: "08 Мая 2024, 21:00",
    status: "success",
  },
  {
    id: "tx-4",
    gameId: "roblox",
    amount: 200,
    date: "05 Мая 2024, 16:45",
    status: "success",
  },
  {
    id: "tx-5",
    gameId: "arena-breakout",
    amount: 500,
    date: "01 Мая 2024, 12:20",
    status: "success",
  },
  {
    id: "tx-6",
    gameId: "epic",
    amount: 1000,
    date: "28 Апр 2024, 18:30",
    status: "success",
  },
];
