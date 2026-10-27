import { useState } from "react";
import { Modal, Button, TextInput, Label, Alert } from "flowbite-react";
import { HiMail, HiLockClosed, HiUser, HiExclamation } from "react-icons/hi";
import { useAuth } from "../contexts/AuthContext";

type Tab = "login" | "register";

export default function AuthModal() {
  const { showAuthModal, setShowAuthModal, login, register } = useAuth();
  const [tab, setTab] = useState<Tab>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [username, setUsername] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const reset = () => {
    setEmail("");
    setPassword("");
    setUsername("");
    setConfirmPw("");
    setError("");
  };

  const switchTab = (t: Tab) => {
    setTab(t);
    reset();
  };

  const handleLogin = async () => {
    setError("");
    if (!email || !password) { setError("Please fill in all fields"); return; }
    setSubmitting(true);
    const err = await login(email, password);
    setSubmitting(false);
    if (err) setError(err);
    else reset();
  };

  const handleRegister = async () => {
    setError("");
    if (!username || !email || !password || !confirmPw) { setError("Please fill in all fields"); return; }
    if (password !== confirmPw) { setError("Passwords do not match"); return; }
    if (password.length < 6) { setError("Password must be at least 6 characters"); return; }
    setSubmitting(true);
    const err = await register(username, email, password);
    setSubmitting(false);
    if (err) setError(err);
    else reset();
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      tab === "login" ? handleLogin() : handleRegister();
    }
  };

  return (
    <Modal show={showAuthModal} size="md" onClose={() => { setShowAuthModal(false); reset(); }} popup>
      <Modal.Header />
      <Modal.Body>
        <div className="space-y-4" onKeyDown={onKeyDown}>
          <div className="mb-2">
            <p className="text-xs font-bold uppercase tracking-[0.14em] text-blue-600">DFThub account</p>
            <h2 className="mt-1 text-2xl font-semibold tracking-[-0.03em] text-gray-900 dark:text-white">Welcome back</h2>
            <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">Sign in to continue your research workspace.</p>
          </div>
          {/* Tabs */}
          <div className="flex rounded-xl bg-gray-100 p-1 dark:bg-gray-800" role="tablist" aria-label="Account access">
            <button
              type="button"
              role="tab"
              aria-selected={tab === "login"}
              className={`apple-press flex-1 rounded-lg py-2 text-center text-sm font-medium transition-colors ${tab === "login" ? "bg-white text-gray-900 shadow-sm dark:bg-gray-700 dark:text-white" : "text-gray-500 hover:text-gray-700 dark:text-gray-400"}`}
              onClick={() => switchTab("login")}
            >
              Sign In
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === "register"}
              className={`apple-press flex-1 rounded-lg py-2 text-center text-sm font-medium transition-colors ${tab === "register" ? "bg-white text-gray-900 shadow-sm dark:bg-gray-700 dark:text-white" : "text-gray-500 hover:text-gray-700 dark:text-gray-400"}`}
              onClick={() => switchTab("register")}
            >
              Register
            </button>
          </div>

          {error && (
            <Alert color="failure" icon={HiExclamation} role="alert">
              {error}
            </Alert>
          )}

          {tab === "login" ? (
            <>
              <div>
                <Label htmlFor="login-email" value="Email" />
                <TextInput id="login-email" type="email" icon={HiMail} autoComplete="email" required placeholder="you@example.com"
                  value={email} onChange={(e) => setEmail(e.target.value)} />
              </div>
              <div>
                <Label htmlFor="login-pw" value="Password" />
                <TextInput id="login-pw" type="password" icon={HiLockClosed} autoComplete="current-password" required placeholder="••••••"
                  value={password} onChange={(e) => setPassword(e.target.value)} />
              </div>
              <Button className="apple-press w-full rounded-full" onClick={handleLogin} disabled={submitting} aria-busy={submitting}>
                {submitting ? "Signing in..." : "Sign In"}
              </Button>
              <p className="text-sm text-gray-500 dark:text-gray-400 text-center">
                No account?{" "}
                <button className="text-blue-600 hover:underline" onClick={() => switchTab("register")}>
                  Register
                </button>
              </p>
            </>
          ) : (
            <>
              <div>
                <Label htmlFor="reg-name" value="Username" />
                <TextInput id="reg-name" type="text" icon={HiUser} autoComplete="username" required placeholder="your_name"
                  value={username} onChange={(e) => setUsername(e.target.value)} />
              </div>
              <div>
                <Label htmlFor="reg-email" value="Email" />
                <TextInput id="reg-email" type="email" icon={HiMail} autoComplete="email" required placeholder="you@example.com"
                  value={email} onChange={(e) => setEmail(e.target.value)} />
              </div>
              <div>
                <Label htmlFor="reg-pw" value="Password" />
                <TextInput id="reg-pw" type="password" icon={HiLockClosed} autoComplete="new-password" required placeholder="At least 6 characters"
                  value={password} onChange={(e) => setPassword(e.target.value)} />
              </div>
              <div>
                <Label htmlFor="reg-pw2" value="Confirm Password" />
                <TextInput id="reg-pw2" type="password" icon={HiLockClosed} autoComplete="new-password" required placeholder="••••••"
                  value={confirmPw} onChange={(e) => setConfirmPw(e.target.value)} />
              </div>
              <Button className="apple-press w-full rounded-full" onClick={handleRegister} disabled={submitting} aria-busy={submitting}>
                {submitting ? "Registering..." : "Create Account"}
              </Button>
              <p className="text-sm text-gray-500 dark:text-gray-400 text-center">
                Already have an account?{" "}
                <button className="text-blue-600 hover:underline" onClick={() => switchTab("login")}>
                  Sign In
                </button>
              </p>
            </>
          )}
        </div>
      </Modal.Body>
    </Modal>
  );
}
