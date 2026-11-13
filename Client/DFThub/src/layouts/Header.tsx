import {
  Navbar,
  DarkThemeToggle,
  Dropdown,
  Avatar,
  Button,
  Flowbite,
} from "flowbite-react";
import { HiArrowSmRight, HiUser, HiViewBoards, HiLogin, HiSparkles } from "react-icons/hi";
import { useAuth } from "../contexts/AuthContext";

function LogoTitle() {
  return (
    <Navbar.Brand href="/" className="gap-3">
      <span className="brand-mark" aria-hidden="true"><HiSparkles className="h-5 w-5" /></span>
      <span className="self-center whitespace-nowrap text-lg font-semibold tracking-[-0.02em] text-gray-900 dark:text-white">
        DFThub
      </span>
    </Navbar.Brand>
  );
}

function UserLogin() {
  const { user, isAuthenticated, logout, setShowAuthModal } = useAuth();

  if (!isAuthenticated) {
    return (
      <div className="flex items-center gap-2 md:order-2">
        <Button
          size="sm"
          color="blue"
          className="apple-press rounded-full px-4 transition-transform active:scale-[.97]"
          onClick={() => setShowAuthModal(true)}
        >
          <HiLogin className="mr-1 h-4 w-4" /> Sign In
        </Button>
        <Flowbite><DarkThemeToggle className="rounded-full" /></Flowbite>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2 md:order-2">
      <Dropdown
        arrowIcon={false}
        inline={true}
        label={
          <span aria-label="Open account menu" title="Open account menu">
            <Avatar
              alt="User settings"
              placeholderInitials={user!.username.slice(0, 2).toUpperCase()}
              rounded={true}
              bordered={true}
              className="transition-transform active:scale-[.96]"
            />
          </span>
        }
      >
        <Dropdown.Header>
          <span className="block text-sm">{user!.username}</span>
          <span className="block truncate text-sm font-medium">{user!.email}</span>
        </Dropdown.Header>
        <Dropdown.Item icon={HiViewBoards}>Tasks</Dropdown.Item>
        <Dropdown.Item icon={HiUser}>Profile</Dropdown.Item>
        <Dropdown.Item icon={HiArrowSmRight} onClick={logout}>Sign out</Dropdown.Item>
        <Dropdown.Divider />
        <Flowbite><DarkThemeToggle className="mx-auto rounded-full" /></Flowbite>
      </Dropdown>
    </div>
  );
}

export default function Header() {
  return (
    <header className="site-header">
      <Navbar fluid rounded className="glass-nav px-4 py-3">
        <LogoTitle />
        <UserLogin />
      </Navbar>
    </header>
  );
}
