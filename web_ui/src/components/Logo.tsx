import React from 'react';
import Image from 'next/image';

export const Logo = ({ className = "w-8 h-8" }: { className?: string }) => (
  <div className={`relative ${className}`}>
    <Image
        src="/solidai-sre-logo.png"
        alt="SolidAI SRE Logo"
        fill
        className="object-contain"
    />
  </div>
);

export const LogoFull = () => (
    <div className="relative h-full w-full flex-shrink-0">
        <Image
            src="/solidai-sre-logo.png"
            alt="SolidAI SRE"
            fill
            className="object-contain object-left"
        />
    </div>
);
