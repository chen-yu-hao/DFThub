import { HiMail } from "react-icons/hi";

function FootMap() {
  return (
    <footer className="footer-shell px-4 py-8 text-sm text-gray-500 dark:text-gray-400">
      <div className="mx-auto flex max-w-[1180px] flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <a href="/" className="flex items-center gap-2 font-semibold text-gray-800 transition-opacity hover:opacity-70 dark:text-gray-200">
          <span className="brand-mark h-7 w-7 rounded-lg"><span className="text-xs">D</span></span>
          DFThub
        </a>
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
          <a className="inline-flex items-center gap-1.5 transition-colors hover:text-blue-600" href="mailto:ECNU_DFThub@163.com">
            <HiMail className="h-4 w-4" /> ECNU_DFThub@163.com
          </a>
        </div>
      </div>
    </footer>
  );
}

export default FootMap;
