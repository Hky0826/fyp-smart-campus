import React, { useState } from 'react';

const LoginScreen = ({ handleLogin, loginEmail, setLoginEmail, loginPassword, setLoginPassword, loginError }) => {
    const [showPassword, setShowPassword] = useState(false);

    return (
        <div className="flex justify-center items-center min-height-screen h-screen bg-slate-950 font-['Outfit'] relative overflow-hidden">
            {/* Background blobs for premium depth */}
            <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-blue-600 rounded-full mix-blend-multiply filter blur-3xl opacity-20 animate-pulse"></div>
            <div className="absolute bottom-1/4 right-1/4 w-96 h-96 bg-purple-600 rounded-full mix-blend-multiply filter blur-3xl opacity-20 animate-pulse delay-700"></div>
            
            <form onSubmit={handleLogin} className="bg-slate-900/80 backdrop-blur-xl border border-slate-800 p-10 rounded-2xl shadow-2xl w-96 relative z-10">
                <div className="flex flex-col items-center mb-8">
                    <div className="w-12 h-12 bg-blue-600 rounded-xl flex items-center justify-center mb-4 shadow-lg shadow-blue-500/30">
                        <svg className="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 20l-5.447-2.724A2 2 0 013 15.556V4.444a2 2 0 011.553-1.782l5.447-1.362a2 2 0 011.553 0l5.447 1.362A2 2 0 0119 4.444v11.112a2 2 0 01-1.553 1.782L12 20M9 20l3-1.5M9 20V11m3 7.5v-8" />
                        </svg>
                    </div>
                    <h2 className="text-2xl font-bold text-white tracking-wide">Campus Navigation</h2>
                    <p className="text-slate-400 text-sm mt-1">Admin Portal Control Panel</p>
                </div>

                {loginError && (
                    <div className="bg-red-950/50 border border-red-500/50 text-red-200 text-sm p-3 rounded-lg mb-6 text-center font-medium">
                        {loginError}
                    </div>
                )}

                <div className="mb-5">
                    <label className="block text-slate-400 text-xs font-bold uppercase tracking-wider mb-2">Email Address</label>
                    <input 
                        type="email" 
                        value={loginEmail} 
                        onChange={e => setLoginEmail(e.target.value)} 
                        required 
                        placeholder="Enter your Email Address"
                        className="w-full bg-slate-950 border border-slate-800 rounded-lg py-3 px-4 text-white placeholder-slate-650 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition-all duration-200"
                    />
                </div>

                <div className="mb-8 relative">
                    <label className="block text-slate-400 text-xs font-bold uppercase tracking-wider mb-2">Password</label>
                    <div className="relative">
                        <input 
                            type={showPassword ? "text" : "password"} 
                            value={loginPassword} 
                            onChange={e => setLoginPassword(e.target.value)} 
                            required 
                            placeholder="Enter your Password"
                            className="w-full bg-slate-950 border border-slate-800 rounded-lg py-3 pl-4 pr-12 text-white placeholder-slate-650 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition-all duration-200"
                        />
                        <button
                            type="button"
                            onClick={() => setShowPassword(!showPassword)}
                            className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-200 focus:outline-none cursor-pointer"
                            title={showPassword ? "Hide Password" : "Show Password"}
                        >
                            {showPassword ? (
                                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
                                </svg>
                            ) : (
                                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                                </svg>
                            )}
                        </button>
                    </div>
                </div>

                <button 
                    type="submit" 
                    className="w-full py-3 bg-blue-600 hover:bg-blue-500 active:bg-blue-700 text-white font-bold rounded-lg shadow-lg shadow-blue-500/20 hover:shadow-blue-500/35 transition-all duration-200 cursor-pointer text-center block border-0"
                >
                    Secure Login
                </button>
            </form>
        </div>
    );
};

export default LoginScreen;