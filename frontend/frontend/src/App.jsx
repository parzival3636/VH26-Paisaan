import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { PipelineProvider } from './context/PipelineContext';
import Layout from './components/layout/Layout';
import Dashboard from './views/Dashboard';
import ControlCenter from './views/ControlCenter';

export default function App() {
  return (
    <PipelineProvider>
      <BrowserRouter>
        <Layout>
          <Routes>
            <Route path="/"         element={<Dashboard />} />
            <Route path="/controls" element={<ControlCenter />} />
          </Routes>
        </Layout>
      </BrowserRouter>
    </PipelineProvider>
  );
}
