import Sidebar from './Sidebar';
import TopBar from './TopBar';
import './Layout.css';

export default function Layout({ children }) {
  return (
    <div className="layout">
      <Sidebar />
      <div className="layout-main">
        <TopBar />
        <main className="layout-content">
          {children}
        </main>
      </div>
    </div>
  );
}
