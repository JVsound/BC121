function val = readFarField(folder,names)
%READFARFIELD Far-field pressures that were exported from Ansys Mechanical, one structure per microphone
%   val = readFarField(folder) reads every pair of files "Far-field Maximum Pressure <name>.txt" and
%   "Far-field Phase <name>.txt" in folder, as exportFarField.py writes them, and returns a structure array
%   with one element per microphone, sorted by name (numbers in a name count as numbers: Mic5m before Mic10m).
%   val = readFarField(folder,names) reads only the microphones in names (a string array, for example
%   ["Mic5m" "Mic10m"]) and returns them in that order.
%
%   Fields of an element:
%       Name        Name of the microphone, the part of the file name after "Far-field Phase " (string)
%       Frequency   Frequencies in [Hz], row vector
%       Amplitude   Maximum pressure in [Pa], row vector
%       Phase       Phase in [deg], row vector
%       Pressure    Complex pressure in [Pa], Amplitude*exp(1i*Phase), row vector
%   An element can be given to PressureFarField of a comp.FeaEnclosure.
%
%   Mechanical exports the amplitude in MPa; the function converts it to Pa. The amplitude and phase file of a
%   microphone must have the same frequencies.
arguments
    folder (1,1) string {mustBeFolder}
    names (1,:) string = string.empty
end
prefixAmplitude = "Far-field Maximum Pressure ";
prefixPhase = "Far-field Phase ";

if isempty(names)
    files = dir(fullfile(folder,prefixAmplitude + "*.txt"));
    names = erase(string({files.name}),[prefixAmplitude ".txt"]);
    names = names(arrayfun(@(n) isfile(fullfile(folder,prefixPhase + n + ".txt")),names));
    if isempty(names)
        error("readFarField:noFiles","No pair ""%s<name>.txt"" and ""%s<name>.txt"" in %s.",prefixAmplitude,prefixPhase,folder)
    end
    names = sortNatural(names);
end

val = struct(Name={},Frequency={},Amplitude={},Phase={},Pressure={});
for k = 1:numel(names)
    amplitudeFile = fullfile(folder,prefixAmplitude + names(k) + ".txt");
    phaseFile = fullfile(folder,prefixPhase + names(k) + ".txt");
    if ~isfile(amplitudeFile) || ~isfile(phaseFile)
        error("readFarField:missingFile","Microphone ""%s"": %s and %s must both exist.",names(k),amplitudeFile,phaseFile)
    end
    amplitude = readmatrix(amplitudeFile,FileType="text",NumHeaderLines=1);
    phase = readmatrix(phaseFile,FileType="text",NumHeaderLines=1);
    if size(amplitude,1) ~= size(phase,1) || max(abs(amplitude(:,1) - phase(:,1))) > 1e-6*max(amplitude(:,1))
        error("readFarField:otherFrequencies","Microphone ""%s"": amplitude and phase have other frequencies.",names(k))
    end
    val(k).Name = names(k);
    val(k).Frequency = amplitude(:,1).';
    val(k).Amplitude = amplitude(:,2).'*1e6;
    val(k).Phase = phase(:,2).';
    val(k).Pressure = val(k).Amplitude.*exp(1i*deg2rad(val(k).Phase));
end
end

function sorted = sortNatural(names)
%SORTNATURAL Sort strings on their text and then on the first number in them, so "Mic5m" comes before "Mic10m"
text = regexprep(names,"\d+(\.\d+)?","#");
number = zeros(size(names));
for k = 1:numel(names)
    first = regexp(names(k),"\d+(\.\d+)?","match","once");
    if ~ismissing(first)
        number(k) = str2double(first);
    end
end
[~,order] = sortrows(table(text(:),number(:)));
sorted = names(order);
end
