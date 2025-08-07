---------------------------------------------------------------------------
-- Universidade Federal de Minas Gerais (UFMG)
---------------------------------------------------------------------------
-- Project: Generic Types
-- Design: package generic_Components
---------------------------------------------------------------------------

library IEEE;
use IEEE.STD_LOGIC_1164.all;

package GENERIC_TYPES is
    -- Define base array type with maximum word length for Reed-Solomon
    -- Maximum is RS_GF_1024 = GF(2^10) = 10-bit symbols
    subtype max_word is std_logic_vector(9 downto 0);
    type std_logic_vector_array is array (natural range <>) of max_word;
    type array_of_integers is array(integer range <>) of integer;
    type integer_array is array(integer range <>) of integer;
end package GENERIC_TYPES;
